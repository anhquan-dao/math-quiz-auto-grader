"""Align one captured page and extract the canonical answer interiors."""

import logging
import math
from pathlib import Path

import cv2
import numpy as np

from .io import read_image, write_image, write_json
from .regions import refine_box, southern_mask
from .template import draw_boxes
from .vision import align, marker_overlay, normalize_light

LOG = logging.getLogger(__name__)


def extract_capture(image_path: Path, template: dict, output: Path,
                    page_number: int = 1, inset_mm: float = .3, *,
                    box_mode: str = "refine", box_search_mm: float = 2.,
                    south_mm: float = 2., keep_south_border: bool = False) -> dict:
    if template.get("schema_version") != 1:
        raise ValueError("Unsupported template schema")
    page = next((p for p in template["pages"] if p["page"] == page_number), None)
    if page is None:
        raise ValueError(f"Template has no page {page_number}")
    if any(not math.isfinite(v) or v < 0 for v in (inset_mm, box_search_mm, south_mm)):
        raise ValueError("Crop inset, box search, and south expansion must be finite and nonnegative")
    if box_mode not in {"template", "refine"}:
        raise ValueError("Box mode must be template or refine")
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
    radius = round(box_search_mm * template["dpi"] / 25.4)
    south = round(south_mm * template["dpi"] / 25.4)
    ink = cv2.bitwise_not(binary)
    regions = [refine_box(ink, box["bbox_px"], radius) if box_mode == "refine" else
               {"bbox_px": list(box["bbox_px"]), "detected": False, "confidence": 0., "edges": {}}
               for box in page["boxes"]]
    refined_boxes = [{"id": b["id"], "bbox_px": r["bbox_px"]}
                     for b, r in zip(page["boxes"], regions)]
    write_image(output / "08_refined_boxes.png", draw_boxes(aligned, refined_boxes))
    answers = []
    page_mask = np.zeros(binary.shape, np.uint8)
    for index, (box, region) in enumerate(zip(page["boxes"], regions)):
        left, top, right, bottom = region["bbox_px"]
        x0, y0, x1 = left + inset, top + inset, right - inset
        # When expanding south, retain the whole lower border and any crossing strokes.
        y1 = min(aligned.shape[0], bottom + south) if south else bottom-inset
        requested_y1 = y1
        for other_index, other in enumerate(regions):
            ox0, oy0, ox1, _ = other["bbox_px"]
            if other_index != index and oy0 >= bottom and min(x1, ox1) > max(x0, ox0):
                y1 = min(y1, oy0-2)
        if not (0 <= x0 < x1 <= aligned.shape[1] and 0 <= y0 < y1 <= aligned.shape[0]):
            raise ValueError(f"Invalid crop for {box['id']}; check inset and template bounds")
        files = {}
        bounds = [x0, y0, x1, y1]
        mask = np.zeros((y1-y0, x1-x0), np.uint8)
        if region["detected"] and not keep_south_border:
            mask = southern_mask(ink, region["edges"]["south"], bounds, template["dpi"])
        page_mask[y0:y1, x0:x1] |= mask
        for name, image in (("raw", aligned), ("normalized", normalized), ("binary", binary)):
            relative = f"crops/{box['id']}_{name}.png"
            crop = image[y0:y1, x0:x1].copy()
            if name != "raw":
                crop[mask > 0] = 255
            write_image(output / relative, crop)
            files[name] = relative
        for name, image in (("border_mask", mask),
                            ("normalized_unmasked", normalized[y0:y1, x0:x1])):
            relative = f"crops/{box['id']}_{name}.png"
            write_image(output / relative, image)
            files[name] = relative
        answers.append({"id": box["id"], "template_bbox_px": box["bbox_px"],
                        "frame": region, "bbox_px": bounds, "files": files,
                        "south_expansion_px": max(0, y1-bottom),
                        "expansion_limited": bool(south and y1 < bottom+south),
                        "neighbor_limited": y1 < requested_y1,
                        "border_removed_pixels": cv2.countNonZero(mask)})
        LOG.debug("%s: template=%s frame=%s crop=%s detected=%s removed=%d",
                  box["id"], box["bbox_px"], region["bbox_px"], bounds,
                  region["detected"], cv2.countNonZero(mask))
    write_image(output / "09_crop_areas.png", draw_boxes(aligned, answers))
    write_image(output / "10_border_mask.png", page_mask)
    cleaned = normalized.copy()
    cleaned[page_mask > 0] = 255
    write_image(output / "11_border_removed.png", cleaned)
    result = {"schema_version": 1, "input": str(image_path.resolve()), "page": page_number,
              "alignment": metrics, "answers": answers,
              "crop_options": {"inset_mm": inset_mm, "box_mode": box_mode,
                               "box_search_mm": box_search_mm, "south_mm": south_mm,
                               "keep_south_border": keep_south_border}}
    write_json(output / "extraction.json", result)
    LOG.info("Extracted %d answer regions to %s", len(answers), output)
    return result
