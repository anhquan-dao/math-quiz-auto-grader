"""Align one captured page and extract the canonical answer interiors."""

import logging
import math
from pathlib import Path

import cv2
import numpy as np

from .io import read_image, write_image, write_json
from .regions import (
    DEFAULT_HORIZONTAL_DILATION_WIDTH_PX,
    SOUTH_BORDER_METHODS,
    horizontal_bounds,
    refine_box,
    southern_dilate,
    southern_mask,
)
from .template import draw_boxes
from .vision import align, marker_overlay, normalize_light

LOG = logging.getLogger(__name__)
STAGE_IMAGES = ("01_input.png", "02_illumination.png", "03_markers.png", "04_aligned.png",
                "05_normalized.png", "06_binary.png", "07_boxes.png", "08_refined_boxes.png",
                "09_crop_areas.png", "10_border_mask.png", "11_border_removed.png",
                "02_binary.png", "03_boxes.png", "07_template_boxes.png")
CROP_VARIANTS = ("raw", "normalized", "binary", "border_mask", "normalized_unmasked")


def prune_generated_images(output: Path, answers: list[dict], debug_images: bool) -> None:
    """Remove obsolete known image artifacts after a successful extraction, never user files."""
    keep = {"01_input.png", "02_binary.png", "03_boxes.png"}
    keep.update(path for answer in answers for path in answer["files"].values())
    if debug_images:
        keep.update(f"debug/{name}" for name in ("02_illumination.png", "03_markers.png",
                    "04_aligned.png", "05_normalized.png", "07_template_boxes.png",
                    "08_refined_boxes.png", "10_border_mask.png", "11_border_removed.png"))
    candidates = {prefix+name for prefix in ("", "debug/") for name in STAGE_IMAGES}
    candidates.update(f"{folder}/{answer['id']}_{variant}.png" for answer in answers
                      for folder in ("crops", "debug/crops") for variant in CROP_VARIANTS)
    for relative in sorted(candidates-keep):
        target = output / relative
        if target.resolve().is_relative_to(output.resolve()) and target.is_file():
            try:
                target.unlink()
                LOG.debug("Removed obsolete generated image %s", target)
            except OSError:
                LOG.warning("Could not remove obsolete generated image %s", target, exc_info=True)
    for directory in (output / "debug/crops", output / "debug"):
        if (directory.resolve().is_relative_to(output.resolve()) and directory.is_dir()
                and not directory.is_symlink() and not any(directory.iterdir())):
            directory.rmdir()


def extract_capture(image_path: Path, template: dict, output: Path,
                    page_number: int = 1, inset_mm: float = .3, *,
                    box_mode: str = "refine", box_search_mm: float = 2.,
                    south_mm: float = 2., keep_south_border: bool = False,
                    variant: str = "normalized", debug_images: bool = False,
                    tighten_ew: bool = True, tighten_padding_mm: float = 1.5,
                    tighten_mode: str = "both", static_tighten_mm: float = 1.5,
                    south_border_method: str = "bidirectional-recovery",
                    horizontal_dilation_width_px: int = DEFAULT_HORIZONTAL_DILATION_WIDTH_PX) -> dict:
    if template.get("schema_version") != 1:
        raise ValueError("Unsupported template schema")
    page = next((p for p in template["pages"] if p["page"] == page_number), None)
    if page is None:
        raise ValueError(f"Template has no page {page_number}")
    if any(not math.isfinite(v) or v < 0 for v in
           (inset_mm, box_search_mm, south_mm, tighten_padding_mm, static_tighten_mm)):
        raise ValueError("Crop distances and tightening padding must be finite and nonnegative")
    if tighten_mode not in {"static", "dynamic", "both"}:
        raise ValueError("Tighten mode must be static, dynamic, or both")
    if box_mode not in {"template", "refine"}:
        raise ValueError("Box mode must be template or refine")
    if variant not in {"raw", "normalized", "binary"}:
        raise ValueError("Crop variant must be raw, normalized, or binary")
    if south_border_method not in SOUTH_BORDER_METHODS:
        raise ValueError("South border method must be bidirectional-recovery or protected-crossings")
    if (not isinstance(horizontal_dilation_width_px, int) or isinstance(horizontal_dilation_width_px, bool)
            or horizontal_dilation_width_px < 1):
        raise ValueError("Horizontal dilation width must be a positive integer")
    LOG.debug("South border method=%s, horizontal span=%d px, disabled=%s",
              south_border_method, horizontal_dilation_width_px, keep_south_border)
    source = read_image(image_path)
    # Save evidence even when registration fails.
    write_image(output / "01_input.png", source)
    if debug_images:
        write_image(output / "debug/02_illumination.png", normalize_light(source))
    aligned, metrics, markers = align(source, page, template["dictionary"])
    if debug_images:
        write_image(output / "debug/03_markers.png", marker_overlay(source, markers))
        write_image(output / "debug/04_aligned.png", aligned)
    normalized = normalize_light(aligned)
    binary = cv2.adaptiveThreshold(normalized, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 35, 15)
    write_image(output / "02_binary.png", binary)
    if debug_images:
        write_image(output / "debug/05_normalized.png", normalized)
        write_image(output / "debug/07_template_boxes.png", draw_boxes(aligned, page["boxes"]))
    inset = round(inset_mm * template["dpi"] / 25.4)
    radius = round(box_search_mm * template["dpi"] / 25.4)
    south = round(south_mm * template["dpi"] / 25.4)
    padding = math.ceil(tighten_padding_mm * template["dpi"] / 25.4)
    static = math.ceil(static_tighten_mm * template["dpi"] / 25.4)
    ink = cv2.bitwise_not(binary)
    regions = [refine_box(ink, box["bbox_px"], radius) if box_mode == "refine" else
               {"bbox_px": list(box["bbox_px"]), "detected": False, "confidence": 0., "edges": {}}
               for box in page["boxes"]]
    if debug_images:
        refined_boxes = [{"id": b["id"], "bbox_px": r["bbox_px"]}
                         for b, r in zip(page["boxes"], regions)]
        write_image(output / "debug/08_refined_boxes.png", draw_boxes(aligned, refined_boxes))
    answers = []
    page_mask = np.zeros(binary.shape, np.uint8) if debug_images else None
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
        border = {"method": south_border_method, "applied": False}
        if region["detected"] and not keep_south_border:
            border["applied"] = True
            if south_border_method == "bidirectional-recovery":
                recovery = southern_dilate(ink, region["edges"]["south"], bounds, template["dpi"],
                                             horizontal_dilation_width_px=horizontal_dilation_width_px)
                mask = recovery["removed_mask"]
                border.update({name: recovery[name] for name in (
                    "band_height_px", "kernel_height_px", "strip_padding_px",
                    "horizontal_dilation_width_px", "horizontal_sum_threshold", "thickness_estimate")})
            else:
                mask = southern_mask(ink, region["edges"]["south"], bounds, template["dpi"])
        before_tightening = list(bounds)
        if tighten_ew and tighten_mode in {"static", "both"}:
            if 2*static >= x1-x0:
                raise ValueError(f"Static tightening would empty {box['id']} ({x1-x0} px wide); "
                                 "reduce --static-tighten-mm")
            mask = mask[:, static:mask.shape[1]-static]
            x0, x1 = x0+static, x1-static
            bounds = [x0, y0, x1, y1]
            LOG.debug("%s: static east/west tightening %d px per side -> %s", box['id'], static, bounds)
        after_static = list(bounds)
        if tighten_ew and tighten_mode in {"dynamic", "both"}:
            measurement = binary[y0:y1, x0:x1].copy()
            measurement[mask > 0] = 255
            west, east = horizontal_bounds(measurement, padding, frame=region,
                                           origin=(x0, y0), dpi=template["dpi"])
            mask = mask[:, west:east]
            x0, x1 = x0+west, x0+east
            bounds = [x0, y0, x1, y1]
        if debug_images:
            page_mask[y0:y1, x0:x1] |= mask
        for name, image in (("raw", aligned), ("normalized", normalized), ("binary", binary)):
            if name not in {variant, "binary"} and not debug_images:
                continue
            folder = "crops" if name in {variant, "binary"} else "debug/crops"
            relative = f"{folder}/{box['id']}_{name}.png"
            crop = image[y0:y1, x0:x1].copy()
            if name != "raw":
                crop[mask > 0] = 255
            if name == "normalized":
                crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
                crop[mask > 0] = (0, 0, 255)
            write_image(output / relative, crop)
            files[name] = relative
        if debug_images:
            for name, image in (("border_mask", mask),
                                ("normalized_unmasked", normalized[y0:y1, x0:x1])):
                relative = f"debug/crops/{box['id']}_{name}.png"
                write_image(output / relative, image)
                files[name] = relative
        answers.append({"id": box["id"], "template_bbox_px": box["bbox_px"],
                        "frame": region, "bbox_px": bounds, "files": files, "south_border": border,
                        "pre_tighten_bbox_px": before_tightening,
                        "post_static_bbox_px": after_static,
                        "static_tighten_ew_px": {"west": after_static[0]-before_tightening[0],
                                                 "east": before_tightening[2]-after_static[2]},
                        "dynamic_tighten_ew_px": {"west": x0-after_static[0],
                                                  "east": after_static[2]-x1},
                        "tighten_ew_px": {"west": x0-before_tightening[0],
                                          "east": before_tightening[2]-x1},
                        "south_expansion_px": max(0, y1-bottom),
                        "normalized_overlay": ("south_border_mask_red" if
                                               "normalized" in files and cv2.countNonZero(mask) else None),
                        "expansion_limited": bool(south and y1 < bottom+south),
                        "neighbor_limited": y1 < requested_y1,
                        "border_removed_pixels": cv2.countNonZero(mask)})
        LOG.debug("%s: template=%s frame=%s crop=%s detected=%s removed=%d",
                  box["id"], box["bbox_px"], region["bbox_px"], bounds,
                  region["detected"], cv2.countNonZero(mask))
    write_image(output / "03_boxes.png", draw_boxes(aligned, answers))
    if debug_images:
        write_image(output / "debug/10_border_mask.png", page_mask)
        cleaned = normalized.copy()
        cleaned[page_mask > 0] = 255
        write_image(output / "debug/11_border_removed.png", cleaned)
    result = {"schema_version": 1, "input": str(image_path.resolve()), "page": page_number,
              "alignment": metrics, "answers": answers, "crop_variant": variant,
              "debug_images": debug_images,
              "crop_options": {"inset_mm": inset_mm, "box_mode": box_mode,
                               "box_search_mm": box_search_mm, "south_mm": south_mm,
                               "keep_south_border": keep_south_border,
                               "south_border_method": south_border_method,
                               "horizontal_dilation_width_px": horizontal_dilation_width_px,
                               "tighten_ew": tighten_ew, "tighten_padding_mm": tighten_padding_mm,
                               "tighten_mode": tighten_mode, "static_tighten_mm": static_tighten_mm}}
    write_json(output / "extraction.json", result)
    prune_generated_images(output, answers, debug_images)
    LOG.info("Extracted %d answer regions to %s", len(answers), output)
    return result
