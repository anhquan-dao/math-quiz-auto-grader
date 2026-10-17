"""Shared logging and Unicode-safe image/JSON I/O."""

import json
import logging
from pathlib import Path

import cv2
import numpy as np

LOG = logging.getLogger(__name__)


def configure_logging(path: Path, verbose: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    logging.getLogger().handlers[1].setLevel(logging.DEBUG if verbose else logging.INFO)


def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot decode image: {path}")
    LOG.debug("Read %s: shape=%s", path, image.shape)
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix, image)
    if not ok:
        raise ValueError(f"Cannot encode image: {path}")
    encoded.tofile(path)
    LOG.debug("Wrote %s: shape=%s", path, image.shape)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    LOG.debug("Wrote %s", path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
