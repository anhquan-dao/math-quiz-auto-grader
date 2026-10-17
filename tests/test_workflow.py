import cv2
import numpy as np
import pytest

from automarker.io import read_json, write_image, write_json
from automarker.vision import detect_markers
from automarker.workflow import collect_images, process_captures


def test_collect_images_filters_inputs_and_rejects_collisions(tmp_path):
    (tmp_path / "notes.txt").write_text("not an image", encoding="utf-8")
    photo = tmp_path / "photo.JPG"
    photo.touch()
    (tmp_path / "folder.png").mkdir()
    assert collect_images([tmp_path]) == [photo]
    duplicate = tmp_path / "photo.png"
    duplicate.touch()
    with pytest.raises(ValueError, match="unique"):
        collect_images([tmp_path])
    with pytest.raises(ValueError, match="does not exist"):
        collect_images([tmp_path / "missing.jpg"])


def test_batch_continues_after_bad_capture_and_clears_stale_failure(tmp_path):
    image = np.full((800, 600, 3), 255, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_1000)
    for marker_id, x, y in [(0, 20, 20), (1, 500, 700)]:
        tag = cv2.aruco.generateImageMarker(dictionary, marker_id, 80)
        image[y:y+80, x:x+80] = cv2.cvtColor(tag, cv2.COLOR_GRAY2BGR)
    cv2.putText(image, "x + 1", (210, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    markers = detect_markers(image, "DICT_4X4_1000")
    template = {"schema_version": 1, "dpi": 100, "dictionary": "DICT_4X4_1000",
                "pages": [{"page": 1, "size_px": [600, 800],
                           "markers": {str(k): v.tolist() for k, v in markers.items()},
                           "boxes": [{"id": "answer_001", "bbox_px": [200, 300, 400, 350]}]}]}
    bad, good = tmp_path / "bad.png", tmp_path / "good.png"
    bad.write_bytes(b"invalid image")
    write_image(good, image)
    output = tmp_path / "captures"
    write_json(output / "good/failure.json", {"error": "obsolete failure"})
    write_json(output / "good/recognition.json", {"stale": True})
    write_json(output / "good/comparison.json", {"stale": True})
    summary = process_captures([bad, good], template, output)
    assert summary["successful"] == [str(good)]
    assert summary["failed"][0]["input"] == str(bad)
    assert summary["failed"][0]["stage"] == "extract"
    assert not (output / "good/failure.json").exists()
    assert not (output / "good/recognition.json").exists()
    assert not (output / "good/comparison.json").exists()
    assert (output / "good/extraction.json").is_file()
    assert read_json(output / "summary.json") == summary
