"""Portable offline HTML review archives with crops, OCR, and answer keys."""

import base64
import json
import logging
import re
import zipfile
from functools import lru_cache
from html import escape
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

from .assessment import FIELDS, assessment_rows, ensure_assessment
from .grading import compare_answers
from .io import read_json, write_json

LOG = logging.getLogger(__name__)
ASSETS = Path(__file__).parent / "assets"
DEMO_FORMULAS = (
    "-2", "2", r"-\sqrt{4-x^2}", r"\sqrt{4-x^2}", "x^2+y^2-2",
    r"4-\sqrt{x^2+y^2}", "-2", "2", "0", "4-x^2", "0", "3+y", "59.7333",
)
DEMO_NOTE = "Made-up expected answers for visualization only. Not a real answer key or a grade."


def demo_key(ids: list[str]) -> dict:
    return {"demo": True, "note": DEMO_NOTE,
            "answers": {answer_id: {"mode": "exact", "value": DEMO_FORMULAS[i % len(DEMO_FORMULAS)]}
                        for i, answer_id in enumerate(ids)}}


@lru_cache(maxsize=1)
def _math_assets() -> tuple[str, str]:
    root = ASSETS / "katex"
    css = (root / "katex.min.css").read_text(encoding="utf-8")

    def inline_font(match: re.Match) -> str:
        font = re.search(r"fonts/([^\"'()]+\.woff2)", match[1])
        if font is None:
            return match[0]
        encoded = base64.b64encode((root / "fonts" / font[1]).read_bytes()).decode("ascii")
        return f'src:url(data:font/woff2;base64,{encoded}) format("woff2");'

    css = re.sub(r"src:([^;]+);", inline_font, css)
    script = (root / "katex.min.js").read_text(encoding="utf-8")
    license_text = (root / "LICENSE").read_text(encoding="utf-8").replace("*/", "* /")
    script += "\n/*\n" + license_text + "\n*/"
    # Keep the script element boundary intact when embedding third-party JavaScript.
    return css, script.replace("</script", r"<\/script")


def _document(title: str, body: str, math: bool = False, review: dict | None = None) -> str:
    css = (ASSETS / "report.css").read_text(encoding="utf-8")
    script = ""
    if math:
        math_css, math_js = _math_assets()
        css += "\n" + math_css
        script = f"<script>{math_js}</script>" + """<script>
document.querySelectorAll('[data-tex]').forEach(function (element) {
  try {
    katex.render(element.dataset.tex, element, {
      displayMode: true, throwOnError: true, trust: false,
      strict: 'ignore', maxSize: 20, maxExpand: 1000
    });
  } catch (error) {
    element.textContent = 'Preview unavailable; see TeX below.';
    element.classList.add('render-error');
  }
});
</script>"""
    if review is not None:
        payload = json.dumps(review, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
        script += f'<script id="assessment-data" type="application/json">{payload}</script>'
        script += "<script>" + (ASSETS / "review.js").read_text(encoding="utf-8") + "</script>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:;
font-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none';">
<title>{escape(title)} | AutoMarker</title><style>{css}</style></head>
<body><main>{body}<footer>AutoMarker &middot; Local review archive &middot;
OCR suggestions and reviewer verdicts are stored separately.</footer></main>{script}</body></html>"""


def _review_tools(command: str, paper: bool = False, last: bool = False) -> str:
    buttons = ""
    if paper:
        buttons += ('<button type="button" data-toggle-latex aria-controls="answer-table" '
                    'aria-pressed="false">Show recognized LaTeX</button>'
                    '<button type="button" data-reload-csv>Reload saved verdicts</button>'
                    '<button type="button" data-save-page>Save page</button>'
                    f'<button type="button" class="primary" data-save-next>'
                    f'{"Save &amp; finish" if last else "Save &amp; next"}</button>')
    tools = (f'<section class="review-toolbar" aria-label="Assessment CSV controls">'
             f'<div class="review-actions">{buttons}'
             '</div>'
             '<p id="assessment-status" role="status" aria-live="polite">'
             'Loading this quiz’s assessment.csv…</p>'
             '<p class="hint">CSV updates require your approval for each paper. '
             'The assessment file belongs to this quiz automatically.</p>'
             '<details class="server-help"><summary>Reviewing a local HTML file?</summary>'
             '<p>Start the offline reviewer from your project environment:</p>'
             f'<pre><code>{escape(command)}</code></pre></details></section>')
    if paper:
        tools += ('<dialog id="save-permission" aria-labelledby="save-title">'
                  '<h2 id="save-title">Allow CSV update for this paper?</h2>'
                  '<p id="save-summary"></p><p>The file will stay unchanged unless you allow this update.</p>'
                  '<div class="dialog-actions"><button type="button" id="cancel-save">Cancel</button>'
                  '<button type="button" class="primary" id="approve-save">Allow CSV update</button>'
                  '</div></dialog>')
    return tools


def _banner(demo: bool) -> str:
    if demo:
        return f'<aside class="notice demo"><strong>DEMO EXPECTED ANSWERS</strong><p>{DEMO_NOTE}</p></aside>'
    return '<aside class="notice">Review the crop and OCR before using any answer-key comparison.</aside>'


def _image(capture: Path, relative: str, label: str) -> str:
    path = (capture / relative).resolve()
    if not path.is_relative_to(capture.resolve()):
        raise ValueError(f"Crop path escapes capture directory: {relative}")
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp"}.get(path.suffix.lower())
    if mime is None:
        raise ValueError(f"Unsupported report image format: {path.suffix}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<img src="data:{mime};base64,{encoded}" alt="{escape(label, quote=True)}">'


def _formula(latex: str | None, empty: str) -> str:
    if not latex:
        return f'<p class="empty">{escape(empty)}</p>'
    value = escape(latex, quote=True)
    return (f'<div class="formula" data-tex="{value}">{value}</div>'
            f'<div class="code-label">TeX source</div><pre><code>{value}</code></pre>')


def _link(filename: str, label: str) -> str:
    return f'<a href="{quote(filename, safe="")}">{escape(label)}</a>'


def _paper_page(record: dict, key: dict, previous: str | None, following: str | None,
                review: dict) -> str:
    data, capture = record["data"], record["capture"]
    demo = bool(key.get("demo"))
    comparisons = ({a["id"]: a["comparison"] for a in compare_answers(data, key)["answers"]}
                   if not demo else {})
    rows = []
    for number, answer in enumerate(data["answers"], start=1):
        answer_id = str(answer["id"])
        files = answer["files"]
        variant = data.get("ocr_variant", data.get("crop_variant", "normalized"))
        if variant not in files:
            variant = next(name for name in ("normalized", "raw", "binary") if name in files)
        crop = _image(capture, files[variant], f"Final crop for {answer_id}")
        overlay = answer.get("normalized_overlay") == "south_border_mask_red"
        if variant == "normalized" and overlay:
            crop += '<p class="hint">Red: removed south-border pixels. OCR uses a clean copy.</p>'
        alternatives = "".join(
            f'<div class="variant"><span>{escape(name.title())}</span>'
            f'{_image(capture, files[name], f"{name} crop for {answer_id}")}</div>'
            for name in ("raw", "normalized", "binary") if name != variant and name in files
        )
        if alternatives:
            crop += f'<details><summary>Other crop versions</summary>{alternatives}</details>'
        ocr = answer.get("ocr", {})
        recognized = _formula(ocr.get("latex"), "OCR has not been run for this answer.")
        if ocr.get("truncated"):
            recognized = '<span class="badge warning">Generation truncated</span>' + recognized
        expected = key.get("answers", {}).get(answer_id)
        expected_html = _formula(str(expected["value"]) if expected else None,
                                 "No expected answer supplied.")
        status, status_class = "No answer key", "muted"
        if demo:
            status, status_class = "Demo value only", "demo-badge"
        elif expected:
            status = {"match": "Text / numeric match", "no_match": "Review difference",
                      "unkeyed": "No answer key"}[comparisons[answer_id]]
            status_class = "match" if comparisons[answer_id] == "match" else "warning"
        if expected and expected.get("mode") == "numeric":
            expected_html += (f'<p class="hint">Absolute tolerance: '
                              f'{escape(str(expected.get("tolerance", "0")))}</p>')
        seed = next(row for row in review["rows"] if row["answer_id"] == answer_id)
        saved = next((row for row in review["savedRows"] if row["answer_id"] == answer_id), seed)
        auto = seed["auto_verdict"]
        automatic = f"Auto: {auto.title()}" if auto else "No auto verdict: expected answer missing"
        buttons = "".join(
            f'<button type="button" class="verdict-button {value}" data-verdict="{value}" '
            f'aria-label="{value.title()} for {escape(answer_id, quote=True)}" '
            f'aria-pressed="{str(saved["verdict"] == value).lower()}">{symbol}</button>'
            for value, symbol in (("correct", "&#10003;"), ("incorrect", "&#10007;")))
        rows.append(f"""<tr><td><div class="answer-heading"><span class="number">{number:02d}</span>
<strong>{escape(answer_id)}</strong><span class="crop-label">{variant}</span></div>
<div class="crop">{crop}</div></td><td class="recognized-latex-column"><span class="cell-label">Recognized LaTeX</span>
{recognized}</td><td><span class="cell-label">Expected answer</span>
<span class="badge {status_class}">{status}</span>{expected_html}</td>
<td class="review-cell" data-review-answer="{escape(answer_id, quote=True)}">
<p class="auto-verdict {auto}">{escape(automatic)}</p>
<div class="verdict-buttons" role="group" aria-label="Verdict for {escape(answer_id, quote=True)}">{buttons}</div>
<label for="notes-{number}">Review notes</label><textarea id="notes-{number}" rows="3"
aria-label="Notes for {escape(answer_id, quote=True)}" placeholder="Optional notes"></textarea></td></tr>""")
    nav = _link("index.html", "All papers")
    nav += _link(previous, "Previous paper") if previous else ""
    nav += _link(following, "Next paper") if following else ""
    name = escape(record["name"])
    recognized_count = sum(bool(a.get("ocr", {}).get("latex")) for a in data["answers"])
    body = f"""<div class="eyebrow">AUTOMARKER / PAPER REVIEW</div><nav>{nav}</nav>
<header><h1>{name}</h1><p class="subtitle">Page {escape(str(data.get('page', 1)))} &middot;
{len(rows)} answer regions &middot; {recognized_count} recognized</p></header>{_banner(demo)}
{_review_tools(review['command'], paper=True, last=following is None)}
<div class="table-wrap"><table id="answer-table" class="answers" data-latex-hidden="true">
<colgroup><col><col class="recognized-latex-column"><col><col></colgroup>
<thead><tr><th scope="col">Final answer crop</th><th scope="col" class="recognized-latex-column">Recognized LaTeX</th>
<th scope="col">Expected answer {'(demo)' if demo else ''}</th><th scope="col">Reviewer verdict</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<div class="review-bottom"><button type="button" data-save-page>Save page</button>
<button type="button" class="primary" data-save-next>
{'Save &amp; next' if following else 'Save &amp; finish'}</button></div>"""
    return _document(record["name"], body, math=True, review=review)


def build_archive(captures: Path, output: Path, key: dict | None = None,
                  demo_expected: bool = False, quiz_name: str | None = None) -> dict:
    """Generate an index, one self-contained HTML per photo, and a portable ZIP.

    Existing JSON remains the machine-readable source. Extraction-only papers stay
    visible with explicit missing-OCR labels. Demo values never become final grades.
    """
    if key is not None and demo_expected:
        raise ValueError("Choose an answer key or made-up demo expectations, not both")
    captures = captures.resolve()
    if output.resolve() == captures:
        raise ValueError("Report output must be separate from the capture directory")
    manifests = sorted(set(captures.glob("*/extraction.json")) |
                       set(captures.glob("*/recognition.json")))
    if (captures / "extraction.json").is_file() or (captures / "recognition.json").is_file():
        manifests += [captures / "extraction.json"]
    directories = sorted({p.parent for p in manifests})
    if not directories:
        raise ValueError(f"No extraction or recognition results found under {captures}")
    records, ids, names = [], [], set()
    for capture in directories:
        if (capture / "failure.json").is_file():
            LOG.warning("Skipping failed capture %s; see its failure.json", capture)
            continue
        recognition = capture / "recognition.json"
        data = read_json(recognition if recognition.exists() else capture / "extraction.json")
        name = PureWindowsPath(data.get("input", capture.name)).name
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name) + ".html"
        if filename.casefold() in names:
            raise ValueError(f"Duplicate source photo filename in report: {name}")
        names.add(filename.casefold())
        records.append({"capture": capture, "data": data, "name": name, "filename": filename})
        for answer in data["answers"]:
            if answer["id"] not in ids:
                ids.append(answer["id"])
    if not records:
        raise ValueError("No successful captures available for an HTML archive")
    if demo_expected:
        key = demo_key(ids)
    key = key if key is not None else {"answers": {}}
    output.mkdir(parents=True, exist_ok=True)
    archive_id, initial_rows = assessment_rows(records, key)
    saved_rows = ensure_assessment(output / "assessment.csv", initial_rows)
    quiz_name = quiz_name or captures.name
    command = f'automarker review --archive "{output.resolve().as_posix()}" --open'
    generated = []
    pages = []
    for i, record in enumerate(records):
        previous = records[i-1]["filename"] if i else None
        following = records[i+1]["filename"] if i+1 < len(records) else None
        target = output / record["filename"]
        paper_rows = [r for r in initial_rows if r["source_image"] == record["name"] and
                      r["page"] == str(record["data"].get("page", 1))]
        row_ids = {tuple(r[k] for k in FIELDS[:4]) for r in paper_rows}
        snapshot = [r for r in saved_rows if tuple(r[k] for k in FIELDS[:4]) in row_ids]
        review = {"archiveId": archive_id, "fields": FIELDS, "rows": paper_rows,
                  "savedRows": snapshot, "source": record["name"],
                  "page": str(record["data"].get("page", 1)), "command": command,
                  "next": quote(following or "index.html", safe="")}
        target.write_text(_paper_page(record, key, previous, following, review), encoding="utf-8")
        generated.append(target)
        pages.append({"source": record["name"], "html": record["filename"],
                      "answers": len(record["data"]["answers"]),
                      "page": str(record["data"].get("page", 1)),
                      "recognized": sum(bool(a.get("ocr", {}).get("latex"))
                                        for a in record["data"]["answers"])})
        LOG.debug("Wrote paper report %s", target)
    cards = "".join(f'<a class="paper-card" href="{quote(p["html"], safe="")}" '
                    f'data-review-source="{escape(p["source"], quote=True)}" '
                    f'data-review-page="{escape(p["page"], quote=True)}">'
                    f'<span class="paper-number">PAPER {i:02d}</span><h2>{escape(p["source"])}</h2>'
                    f'<p>{p["answers"]} crops &middot; {p["recognized"]} recognized<br>'
                    '<span class="review-progress">Loading saved verdicts</span></p>'
                    '<span class="open-paper">Open paper &rarr;</span></a>'
                    for i, p in enumerate(pages, start=1))
    total = sum(p["answers"] for p in pages)
    recognized = sum(p["recognized"] for p in pages)
    body = f"""<div class="eyebrow">AUTOMARKER / LOCAL REVIEW ARCHIVE</div>
<header><h1>{escape(quiz_name)}</h1><p class="subtitle">Answer crops, recognized math,
and editable reviewer verdicts in one place.</p></header>{_banner(bool(key.get('demo')))}
{_review_tools(command)}
<section class="stats" aria-label="Archive summary"><div><strong>{len(pages)}</strong> papers</div>
<div><strong>{total}</strong> answer crops</div><div><strong>{recognized}</strong> recognized</div></section>
<section class="paper-grid">{cards}</section>"""
    index = output / "index.html"
    index_review = {"archiveId": archive_id, "fields": FIELDS, "rows": initial_rows,
                    "savedRows": saved_rows, "source": None, "page": None, "next": None}
    index.write_text(_document(quiz_name, body, review=index_review), encoding="utf-8")
    generated.append(index)
    write_json(output / "expected.json", key)
    result = {"schema_version": 1, "demo_expected": bool(key.get("demo")), "pages": pages,
              "index": "index.html", "assessment": "assessment.csv", "archive_id": archive_id,
              "quiz_name": quiz_name,
              "note": "Reviewer verdicts are saved to CSV only after explicit per-paper approval."}
    write_json(output / "archive.json", result)
    generated += [output / "expected.json", output / "archive.json", output / "assessment.csv"]
    attribution = output / "THIRD_PARTY_LICENSES.txt"
    provenance = read_json(ASSETS / "katex/provenance.json")
    attribution.write_text(
        f"KaTeX {provenance['version']}\nSource: {provenance['source']}\n\n" +
        (ASSETS / "katex/LICENSE").read_text(encoding="utf-8"), encoding="utf-8")
    generated.append(attribution)
    zip_path = output.with_name(output.name + ".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in generated:
            bundle.write(path, arcname=f"{output.name}/{path.name}")
    LOG.info("HTML archive: %d papers, %d answers; open %s (ZIP: %s)",
             len(pages), total, index, zip_path)
    return result
