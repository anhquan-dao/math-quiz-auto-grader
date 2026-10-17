import csv

import pytest

from automarker.assessment import (
    FIELDS,
    assessment_rows,
    csv_literal,
    ensure_assessment,
    from_csv_literal,
    read_assessment,
)


def example_records():
    return [{"name": "phone,1.jpg", "data": {"page": 1,
             "answers": [{"id": "answer_001", "ocr": {"latex": "-x, y"}}]}}]


def test_csv_roundtrip_prefills_auto_verdict_without_claiming_human_review(tmp_path):
    key = {"answers": {"answer_001": {"mode": "exact", "value": "-x, y"}}}
    archive_id, rows = assessment_rows(example_records(), key)
    rows[0]["notes"] = 'Text "quotes", Vietnamese: đúng\nSecond line'
    path = tmp_path / "assessment.csv"
    ensure_assessment(path, rows)
    restored = read_assessment(path)
    assert restored == rows
    assert restored[0]["suggested_verdict"] == "match"
    assert restored[0]["auto_verdict"] == "correct"
    assert restored[0]["verdict"] == "correct"
    assert restored[0]["reviewed_at"] == ""
    assert restored[0]["archive_id"] == archive_id
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_regeneration_never_overwrites_an_existing_assessment(tmp_path):
    _, rows = assessment_rows(example_records(), {"answers": {}})
    path = tmp_path / "assessment.csv"
    ensure_assessment(path, rows)
    rows[0].update(verdict="incorrect", notes="Reviewer decision", reviewed_at="2026-10-17T10:00:00Z")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    original = path.read_bytes()
    _, fresh = assessment_rows(example_records(), {"answers": {}})
    assert ensure_assessment(path, fresh)[0]["verdict"] == "incorrect"
    assert path.read_bytes() == original


@pytest.mark.parametrize("value", ["-2", "+x", "=1+1", "@value", "'=literal", "\ttext", "x^2", ""])
def test_spreadsheet_literals_are_reversible(value):
    encoded = csv_literal(value)
    assert from_csv_literal(encoded) == value
    assert not encoded or encoded[0] not in "=+-@\t\r"


def test_assessment_rejects_duplicate_answers_and_bad_schema(tmp_path):
    _, rows = assessment_rows(example_records(), {"answers": {}})
    path = tmp_path / "assessment.csv"
    ensure_assessment(path, rows + rows)
    with pytest.raises(ValueError, match="duplicate answer"):
        read_assessment(path)
    path.write_text("source_image,verdict\na.jpg,correct\n", encoding="utf-8")
    with pytest.raises(ValueError, match="headers"):
        read_assessment(path)


def test_changed_recognition_gets_a_distinct_assessment_version():
    first, _ = assessment_rows(example_records(), {"answers": {}})
    records = example_records()
    records[0]["data"]["answers"][0]["ocr"]["latex"] = "changed OCR"
    second, _ = assessment_rows(records, {"answers": {}})
    assert first != second


def test_automatic_verdicts_compare_demo_answers_and_leave_unkeyed_answers_blank():
    records = example_records()
    key = {"demo": True, "answers": {"answer_001": {"mode": "exact", "value": "different"}}}
    _, rows = assessment_rows(records, key)
    assert rows[0]["auto_verdict"] == rows[0]["verdict"] == "incorrect"
    assert rows[0]["demo_expected"] == "true"
    _, unkeyed = assessment_rows(records, {"answers": {}})
    assert unkeyed[0]["auto_verdict"] == unkeyed[0]["verdict"] == ""


def test_migration_prefills_old_unreviewed_rows_and_preserves_human_corrections(tmp_path):
    records = example_records()
    records[0]["data"]["answers"].append({"id": "answer_002", "ocr": {"latex": "x"}})
    key = {"answers": {"answer_001": {"mode": "exact", "value": "-x, y"},
                       "answer_002": {"mode": "exact", "value": "y"}}}
    _, current = assessment_rows(records, key)
    legacy = [{k: v for k, v in row.items() if k != "auto_verdict"} for row in current]
    for row in legacy:
        row.update(archive_id="old-version", verdict="unreviewed")
    legacy[1].update(verdict="correct", notes="Human override", reviewed_at="2026-10-17T10:00:00Z")
    path = tmp_path / "assessment.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(legacy[0]))
        writer.writeheader()
        writer.writerows(legacy)
    saved = ensure_assessment(path, current)
    assert len(saved) == 2
    assert saved[0]["verdict"] == saved[0]["auto_verdict"] == "correct"
    assert saved[0]["reviewed_at"] == ""
    assert saved[1]["auto_verdict"] == "incorrect"
    assert saved[1]["verdict"] == "correct"
    assert saved[1]["notes"] == "Human override"
    before = path.read_bytes()
    ensure_assessment(path, current)
    assert path.read_bytes() == before
