"""Build a reusable canonical template from TeX dimensions and PDF vector geometry."""

import hashlib
import logging
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from .io import write_image, write_json
from .tex import parse_boxes
from .vision import calibrate_markers, find_dictionary, marker_overlay

LOG = logging.getLogger(__name__)


def draw_boxes(image: np.ndarray, boxes: list[dict]) -> np.ndarray:
    out = image.copy()
    for box in boxes:
        x0, y0, x1, y1 = box["bbox_px"]
        cv2.rectangle(out, (x0, y0), (x1, y1), (0, 0, 255), 2)
        cv2.putText(out, box["id"], (x0, y0 - 5), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 0, 255), 1, cv2.LINE_AA)
    return out


def build_template(tex: Path, pdf: Path, output: Path, dpi: int = 200,
                   dictionary: str = "auto", marker_map: dict | None = None,
                   calibration_image: Path | None = None) -> dict:
    if not 72 <= dpi <= 600:
        raise ValueError("DPI must be between 72 and 600")
    specs = parse_boxes(tex)
    scale = dpi / 72
    pages = []
    candidates = []
    with pymupdf.open(pdf) as document:
        if calibration_image and len(document) != 1:
            raise ValueError("Photo calibration currently supports a single-page PDF; "
                             "use --marker-map for multiple pages")
        for page_index, page in enumerate(document):
            if page.rotation:
                raise ValueError("Use an unrotated reference PDF (page rotation must be zero)")
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
            image = cv2.cvtColor(np.frombuffer(pix.samples, np.uint8).reshape(
                pix.height, pix.width, 3), cv2.COLOR_RGB2BGR)
            page_data = {"page": page_index + 1, "size_pt": [page.rect.width, page.rect.height],
                         "size_px": [pix.width, pix.height], "boxes": []}
            if marker_map is not None and calibration_image is not None:
                raise ValueError("Choose a marker map or calibration image, not both")
            if calibration_image is not None:
                from .io import read_image
                name, markers, overlay, metrics = calibrate_markers(
                    image, read_image(calibration_image), dictionary)
                page_data["calibration"] = metrics
                write_image(output.parent / "calibration_matches.png", overlay)
            elif marker_map is not None:
                # Explicit map is in top-left PDF points, with decoded marker-corner order.
                mapped = marker_map["pages"][str(page_index + 1)]
                markers = {int(k): np.array(v, np.float32) * scale for k, v in mapped.items()}
                name = marker_map["dictionary"]
                if len(markers) < 2 or any(v.shape != (4, 2) for v in markers.values()):
                    raise ValueError("Marker map requires >=2 IDs, each with four [x,y] corners")
            else:
                name, markers = find_dictionary(image, dictionary)
            if pages and name != dictionary:
                raise ValueError("All pages must use the same ArUco dictionary")
            dictionary = name
            page_data["markers"] = {str(k): v.tolist() for k, v in markers.items()}
            page_data["reference_image"] = f"page_{page_index + 1:03d}.png"
            write_image(output.parent / page_data["reference_image"], image)
            write_image(output.parent / f"page_{page_index + 1:03d}_markers.png",
                        marker_overlay(image, markers))
            # Rounded tcolorbox paths expose an exact rectangular extent in PDF points.
            seen = set()
            for drawing in page.get_drawings():
                rect = drawing["rect"]
                key = tuple(round(v, 1) for v in rect)
                if key in seen:
                    continue
                if any(abs(rect.width - s["width_pt"]) < 0.75 and
                       abs(rect.height - s["height_pt"]) < 0.75 for s in specs):
                    seen.add(key)
                    candidates.append((page_index, rect))
            pages.append(page_data)
    # Cluster nearby top edges into rows, then sort left-to-right within each row.
    candidates.sort(key=lambda item: (item[0], round(item[1].y0 / 4), item[1].x0))
    if len(candidates) != len(specs):
        raise ValueError(f"TeX has {len(specs)} answer boxes but PDF has {len(candidates)} "
                         "matching vector boxes. Use the compiled PDF from the same TeX; "
                         "raster PDFs and macro-defined boxes are not supported yet.")
    for spec, (page_index, rect) in zip(specs, candidates):
        if abs(rect.width - spec["width_pt"]) >= 2 or abs(rect.height - spec["height_pt"]) >= 2:
            raise ValueError(f"PDF/TeX reading order or dimensions disagree at {spec['id']}")
        box = dict(spec, bbox_pt=list(rect), bbox_px=[round(v * scale) for v in rect])
        pages[page_index]["boxes"].append(box)
    result = {"schema_version": 1, "dpi": dpi, "dictionary": dictionary,
              "tex_sha256": hashlib.sha256(tex.read_bytes()).hexdigest(),
              "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(), "pages": pages}
    for page in pages:
        from .io import read_image
        image = read_image(output.parent / page["reference_image"])
        write_image(output.parent / f"page_{page['page']:03d}_boxes.png",
                    draw_boxes(image, page["boxes"]))
    write_json(output, result)
    LOG.info("Saved template with %d pages, %d boxes to %s", len(pages), len(specs), output)
    return result
