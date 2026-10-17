import socket
from pathlib import Path

import cv2
import numpy as np
import pytest

from automarker.io import write_image
from automarker.ocr import MathOCR

MODEL = Path("models/pix2text-mfr")


@pytest.mark.skipif(not (MODEL / "decoder_model.onnx").exists(),
                    reason="Provision optional OCR model first to run the offline smoke test")
def test_local_math_model_runs_with_network_connections_forbidden(tmp_path, monkeypatch):
    def forbid_network(*args, **kwargs):
        raise AssertionError("Offline OCR attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    image = np.full((80, 260, 3), 255, np.uint8)
    cv2.putText(image, "x + 1", (15, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 2)
    path = tmp_path / "formula.png"
    write_image(path, image)
    result = MathOCR(MODEL).recognize(path, max_tokens=32)
    assert result["latex"]
    assert not result["truncated"]
    assert result["needs_review"]
