"""Align one captured page and extract the canonical answer interiors."""

import logging
from pathlib import Path

import cv2

from .io import read_image, write_image, write_json
from .template import draw_boxes
from .vision import align, marker_overlay, normalize_light

LOG = logging.getLogger(__name__)


def extract_capture(image_path: Path, template: dict, output: Path,
                    page_number: int = 1, inset_mm: float = 1.5) -> dict:
    if template.get("schema_version") != 1:
        raise ValueError("Unsupported template schema")
    page = next((p for p in template["pages"] if p["page"] == page_number), None)
    if page is None:
        raise ValueError(f"Template has no page {page_number}")
    if inset_mm < 0:
        raise ValueError("Crop inset must be nonnegative")
    source = read_image(image_path)
    # Save evidence even when registration fails.
    write_image(output / "01_input.png", source)
    write_image(output / "02_illumination.png", normalize_light(source))
    aligned, metrics, markers = align(source, page, template["dictionary"])
    write_image(output / "03_markers.png", marker_overlay(source, markers))
    write_image(output / "04_aligned.png", aligned)
    normalized = normalize_light(aligned)
    binary = cv2.adaptiveThreshold(normalized, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 35, 15)
    write_image(output / "05_normalized.png", normalized)
    write_image(output / "06_binary.png", binary)
    write_image(output / "07_boxes.png", draw_boxes(aligned, page["boxes"]))
    inset = round(inset_mm * template["dpi"] / 25.4)
    answers = []
    for box in page["boxes"]:
        x0, y0, x1, y1 = box["bbox_px"]
        x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
        if not (0 <= x0 < x1 <= aligned.shape[1] and 0 <= y0 < y1 <= aligned.shape[0]):
            raise ValueError(f"Invalid crop for {box['id']}; check inset and template bounds")
        files = {}
        for name, image in (("raw", aligned), ("normalized", normalized), ("binary", binary)):
            relative = f"crops/{box['id']}_{name}.png"
            write_image(output / relative, image[y0:y1, x0:x1])
            files[name] = relative
        answers.append({"id": box["id"], "bbox_px": [x0, y0, x1, y1], "files": files})
    result = {"schema_version": 1, "input": str(image_path.resolve()), "page": page_number,
              "alignment": metrics, "answers": answers}
    write_json(output / "extraction.json", result)
    LOG.info("Extracted %d answer regions to %s", len(answers), output)
    return result
