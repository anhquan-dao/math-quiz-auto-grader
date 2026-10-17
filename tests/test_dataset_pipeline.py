from pathlib import Path

import cv2
import pytest

from automarker.io import read_image
from automarker.pipeline import extract_capture
from automarker.template import build_template


def test_updated_tagged_pdf_to_all_answer_crops(tmp_path):
    dataset = Path("dataset/Quiz_GT2")
    if not all((dataset / name).is_file() for name in
               ("Quiz_GT2.tex", "Quiz_GT2.pdf", "synthetic/capture_17_desk_shadow.jpg")):
        pytest.skip("Optional local quiz fixtures are not available")
    template = build_template(dataset / "Quiz_GT2.tex", dataset / "Quiz_GT2.pdf",
                              tmp_path / "template.json", dpi=100)
    assert set(template["pages"][0]["markers"]) == {"0", "1"}
    assert len(template["pages"][0]["boxes"]) == 13
    result = extract_capture(dataset / "synthetic/capture_17_desk_shadow.jpg",
                             template, tmp_path / "capture", debug_images=True)
    assert len(result["answers"]) == 13
    assert result["alignment"]["reprojection_rmse_px"] < 1
    for answer in result["answers"]:
        x0, y0, x1, y1 = answer["bbox_px"]
        image = read_image(tmp_path / "capture" / answer["files"]["raw"])
        assert image.shape[:2] == (y1-y0, x1-x0)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        assert (gray < 150).sum() > 10  # Written answers survived rectification and cropping.
