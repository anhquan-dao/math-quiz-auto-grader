"""CSV assessment records shared by generated HTML pages and their review editor."""

import csv
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

from .grading import compare_answers

LOG = logging.getLogger(__name__)
FIELDS = ["archive_id", "source_image", "page", "answer_id", "recognized_latex",
          "expected_latex", "demo_expected", "suggested_verdict", "auto_verdict", "verdict", "notes",
          "reviewed_at"]
VERDICTS = {"", "unreviewed", "correct", "incorrect", "partial"}
CONTEXT_FIELDS = ["source_image", "page", "answer_id", "recognized_latex", "expected_latex", "demo_expected"]
LITERAL_PREFIXES = "=+-@\t\r'"


def csv_literal(value: str) -> str:
    """Escape spreadsheet formula prefixes reversibly; TeX remains literal text."""
    return "'" + value if value and value[0] in LITERAL_PREFIXES else value


def from_csv_literal(value: str) -> str:
    return value[1:] if len(value) > 1 and value[0] == "'" and value[1] in LITERAL_PREFIXES else value


def assessment_rows(records: list[dict], key: dict) -> tuple[str, list[dict]]:
    rows = []
    demo = bool(key.get("demo"))
    for record in records:
        data = record["data"]
        comparisons = {a["id"]: a["comparison"] for a in compare_answers(data, key)["answers"]}
        for answer in data["answers"]:
            expected = key.get("answers", {}).get(answer["id"])
            comparison = comparisons[answer["id"]]
            auto = ("correct" if comparison == "match" else "incorrect") if expected else ""
            rows.append({"source_image": record["name"], "page": str(data.get("page", 1)),
                         "answer_id": str(answer["id"]),
                         "recognized_latex": answer.get("ocr", {}).get("latex", ""),
                         "expected_latex": str(expected["value"]) if expected else "",
                         "demo_expected": "true" if demo else "false",
                         "suggested_verdict": comparison, "auto_verdict": auto,
                         "verdict": auto, "notes": "", "reviewed_at": ""})
    archive_id = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    for row in rows:
        row["archive_id"] = archive_id
    return archive_id, rows


def read_assessment(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        headers = reader.fieldnames or []
        required = set(FIELDS) - {"auto_verdict"}  # Read existing review files before migration.
        if not all(headers) or len(set(headers)) != len(headers) or not required.issubset(headers):
            raise ValueError(f"Assessment CSV has missing or duplicate headers: {path}")
        rows, ids = [], set()
        for raw in reader:
            if None in raw or any(v is None for v in raw.values()):
                raise ValueError(f"Assessment CSV has an invalid row: {path}")
            row = {k: from_csv_literal(v) for k, v in raw.items()}
            row.setdefault("auto_verdict", "")
            identity = tuple(row[k] for k in FIELDS[:4])
            if identity in ids:
                raise ValueError(f"Assessment CSV has duplicate answer rows: {path}")
            if row["verdict"] not in VERDICTS:
                raise ValueError(f"Unknown assessment verdict: {row['verdict']}")
            ids.add(identity)
            rows.append(row)
    return rows


def ensure_assessment(path: Path, rows: list[dict]) -> list[dict]:
    """Initialize auto verdicts and migrate old rows without replacing human decisions."""
    if path.exists():
        saved = read_assessment(path)
        original = [dict(row) for row in saved]
        identities = {tuple(row[k] for k in FIELDS[:4]): i for i, row in enumerate(saved)}
        for seed in rows:
            identity = tuple(seed[k] for k in FIELDS[:4])
            index = identities.get(identity)
            if index is None:
                matches = [i for i, row in enumerate(saved) if
                           all(row[k] == seed[k] for k in CONTEXT_FIELDS)]
                index = matches[-1] if matches else None
            if index is None:
                saved.append(dict(seed))
                continue
            previous = saved[index]
            human = bool(previous["reviewed_at"] or (previous["verdict"] in
                         {"correct", "incorrect", "partial"} and
                         previous["verdict"] != previous["auto_verdict"]))
            saved[index] = {**previous, **seed, "notes": previous["notes"],
                            "verdict": previous["verdict"] if human else seed["verdict"],
                            "reviewed_at": previous["reviewed_at"]}
        if saved != original:
            write_assessment(path, saved)
            LOG.info("Updated automatic assessment rows; retained human decisions: %s", path)
        else:
            LOG.info("Preserved existing assessment CSV: %s", path)
        return saved
    path.parent.mkdir(parents=True, exist_ok=True)
    write_assessment(path, rows)
    LOG.info("Initialized assessment CSV with %d automatic verdicts: %s", len(rows), path)
    return rows


def write_assessment(path: Path, rows: list[dict]) -> None:
    """Replace a complete CSV atomically; retain additional reviewer columns."""
    headers = list(FIELDS)
    for row in rows:
        headers.extend(key for key in row if key not in headers)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="",
                                          dir=path.parent, prefix=".assessment-", suffix=".tmp",
                                          delete=False) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            writer.writerows({k: csv_literal(str(row.get(k, ""))) for k in headers} for row in rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def page_version(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
