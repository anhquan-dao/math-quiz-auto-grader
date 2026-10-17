"""Parse explicit empty tcolorbox dimensions; positions come from the rendered PDF."""

import logging
import re
from pathlib import Path

LOG = logging.getLogger(__name__)
BOX = re.compile(
    r"\\begin\{tcolorbox\}\s*(?:\[(?P<options>.*?)\])?"
    r"(?P<body>.*?)\\end\{tcolorbox\}", re.DOTALL
)
DIMENSION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(cm|mm|pt|bp|in)\s*$")
POINTS = {"cm": 72 / 2.54, "mm": 72 / 25.4, "pt": 72 / 72.27, "bp": 1, "in": 72}


def strip_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%[^\n]*", "", text)


def dimension_pt(value: str) -> float:
    match = DIMENSION.fullmatch(value)
    if not match:
        raise ValueError(f"Expected a literal TeX dimension (cm/mm/pt/bp/in), got {value!r}")
    return float(match[1]) * POINTS[match[2]]


def parse_boxes(path: Path) -> list[dict]:
    """Only empty environments with explicit width AND height are answer boxes.

    This intentionally does not execute TeX, expand macros, or infer page positions
    from source line numbers. Unsupported dimensions fail rather than silently drift.
    """
    source = strip_comments(path.read_text(encoding="utf-8-sig"))
    boxes = []
    for match in BOX.finditer(source):
        if match["body"].strip():
            continue
        options = match["options"] or ""
        values = {}
        for key in ("width", "height"):
            found = re.search(rf"(?:^|,)\s*{key}\s*=\s*([^,]+)", options)
            if found:
                values[key] = dimension_pt(found[1])
        if len(values) != 2:
            raise ValueError("Empty answer tcolorbox requires literal width= and height=")
        box = {"id": f"answer_{len(boxes) + 1:03d}",
               "source_line": source.count("\n", 0, match.start()) + 1,
               "width_pt": values["width"], "height_pt": values["height"]}
        boxes.append(box)
        LOG.debug("TeX box %s", box)
    if not boxes:
        raise ValueError(f"No supported empty answer boxes found in {path}")
    LOG.info("Parsed %d answer boxes from %s", len(boxes), path)
    return boxes
