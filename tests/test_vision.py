import cv2
import numpy as np
import pytest

from automarker.vision import align, detect_markers


def make_page():
    image = np.full((1000, 800, 3), 255, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_1000)
    for marker_id, x, y in [(0, 40, 40), (1, 660, 860)]:
        tag = cv2.aruco.generateImageMarker(dictionary, marker_id, 100)
        image[y:y+100, x:x+100] = cv2.cvtColor(tag, cv2.COLOR_GRAY2BGR)
    cv2.rectangle(image, (180, 420), (600, 490), (0, 0, 0), 2)
    markers = detect_markers(image, "DICT_4X4_1000")
    page = {"size_px": [800, 1000], "markers": {str(k): v.tolist() for k, v in markers.items()},
            "boxes": [{"id": "answer_001", "bbox_px": [180, 420, 600, 490]}]}
    return image, page


def test_recovers_known_perspective_at_answer_box():
    reference, page = make_page()
    source = np.float32([[0, 0], [799, 0], [799, 999], [0, 999]])
    target = np.float32([[160, 90], [850, 160], [940, 1090], [90, 1040]])
    truth = cv2.getPerspectiveTransform(source, target)
    capture = cv2.warpPerspective(reference, truth, (1100, 1200), borderValue=(130, 130, 130))
    _, metrics, _ = align(capture, page, "DICT_4X4_1000")
    probes = np.float32([[[180, 420], [600, 490], [400, 450]]])
    recovered = cv2.perspectiveTransform(cv2.perspectiveTransform(probes, truth),
                                         np.array(metrics["homography"]))
    assert np.max(np.linalg.norm(recovered - probes, axis=2)) < 2.0


def test_rotated_capture_and_missing_tags():
    reference, page = make_page()
    rotated = cv2.rotate(reference, cv2.ROTATE_180)
    aligned, _, _ = align(rotated, page, "DICT_4X4_1000")
    assert np.mean(np.abs(aligned.astype(float) - reference.astype(float))) < 1
    reference[850:980, 650:780] = 255
    with pytest.raises(ValueError, match="shared ArUco"):
        align(reference, page, "DICT_4X4_1000")
