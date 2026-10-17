import re
import zipfile

import numpy as np
import pytest

from automarker.io import read_json, write_image, write_json
from automarker.report import build_archive


def capture_results(root, name="phone photo.jpg", latex=r"x^2 + 1", recognized=True):
    capture = root / "paper"
    write_image(capture / "crops/answer.png", np.full((40, 180, 3), 245, np.uint8))
    data = {"input": "C:/quizzes/" + name, "page": 1,
            "answers": [{"id": "answer_001", "files": {"normalized": "crops/answer.png"}}]}
    write_json(capture / "extraction.json", data)
    if recognized:
        data["answers"][0]["ocr"] = {"latex": latex, "truncated": False}
        write_json(capture / "recognition.json", data)
    return capture


def test_portable_archive_has_filename_pages_inline_images_fonts_and_demo_labels(tmp_path):
    captures, output = tmp_path / "captures", tmp_path / "archive"
    capture_results(captures)
    result = build_archive(captures, output, demo_expected=True)
    assert result["demo_expected"]
    assert result["pages"][0]["html"] == "phone photo.jpg.html"
    page = (output / "phone photo.jpg.html").read_text(encoding="utf-8")
    assert "DEMO EXPECTED ANSWERS" in page
    assert "Demo value only" in page
    assert "Text / numeric match" not in page
    assert "data:image/png;base64," in page
    assert "data:font/woff2;base64," in page
    assert not re.search(r"url\(['\"]?fonts/", page)
    assert 'src="http' not in page
    assert '<script src=' not in page
    assert "x^2 + 1" in page
    index = (output / "index.html").read_text(encoding="utf-8")
    assert "phone%20photo.jpg.html" in index
    assert 'data-link-csv' not in index and 'Link CSV' not in index
    assert 'href="assessment.csv"' not in index
    with zipfile.ZipFile(tmp_path / "archive.zip") as bundle:
        assert set(bundle.namelist()) == {"archive/index.html", "archive/phone photo.jpg.html",
                                          "archive/expected.json", "archive/archive.json",
                                          "archive/THIRD_PARTY_LICENSES.txt", "archive/assessment.csv"}
    assert read_json(output / "expected.json")["demo"]
    assert "Allow CSV update" in page
    assert "Reviewer verdict" in page
    assert 'data-link-csv' not in page
    assert '<select' not in page
    assert 'data-verdict="correct"' in page and 'data-verdict="incorrect"' in page
    assert 'Auto: Incorrect' in page
    assert read_json(output / "archive.json")["assessment"] == "assessment.csv"


def test_expected_key_and_missing_ocr_remain_distinct(tmp_path):
    captures = tmp_path / "captures"
    capture_results(captures, recognized=False)
    key = {"answers": {"answer_001": {"mode": "exact", "value": "EXPECTED_VALUE"}}}
    output = tmp_path / "report"
    build_archive(captures, output, key)
    page = (output / "phone photo.jpg.html").read_text(encoding="utf-8")
    assert "OCR has not been run" in page
    assert "EXPECTED_VALUE" in page
    assert "DEMO EXPECTED ANSWERS" not in page
    assert read_json(output / "archive.json")["pages"][0]["recognized"] == 0


def test_html_escapes_untrusted_recognition_and_rejects_crop_path_traversal(tmp_path):
    capture = capture_results(tmp_path / "captures", latex='</script><img src=x onerror="alert(1)">')
    output = tmp_path / "report"
    build_archive(tmp_path / "captures", output)
    page = (output / "phone photo.jpg.html").read_text(encoding="utf-8")
    assert '&lt;/script&gt;&lt;img src=x onerror=&quot;alert(1)&quot;&gt;' in page
    assert '</script><img src=x' not in page
    data = read_json(capture / "recognition.json")
    data["answers"][0]["files"]["normalized"] = "../../private.png"
    write_json(capture / "recognition.json", data)
    with pytest.raises(ValueError, match="escapes capture"):
        build_archive(tmp_path / "captures", tmp_path / "unsafe")


def test_conflicting_expectations_and_duplicate_photo_names_fail(tmp_path):
    captures = tmp_path / "captures"
    first = capture_results(captures)
    with pytest.raises(ValueError, match="Choose an answer key"):
        build_archive(captures, tmp_path / "report", key={"answers": {}}, demo_expected=True)
    write_json(captures / "second/extraction.json", read_json(first / "extraction.json"))
    with pytest.raises(ValueError, match="Duplicate source photo"):
        build_archive(captures, tmp_path / "report")
