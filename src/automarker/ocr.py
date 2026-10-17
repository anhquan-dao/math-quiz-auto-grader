"""Math OCR with explicit provisioning and strictly local ONNX inference."""

import logging
import os
from pathlib import Path

from .io import read_json, write_json

LOG = logging.getLogger(__name__)
MODEL_ID = "breezedeus/pix2text-mfr"


def download_model(directory: Path, revision: str = "main") -> None:
    """The only OCR operation allowed to contact the model hub."""
    from huggingface_hub import HfApi, snapshot_download

    info = HfApi().model_info(MODEL_ID, revision=revision)
    LOG.info("Downloading %s at revision %s", MODEL_ID, info.sha)
    snapshot_download(repo_id=MODEL_ID, revision=info.sha, local_dir=directory,
                      allow_patterns=["*.json", "*.txt", "*.onnx", "*.model", "README.md"])
    write_json(directory / "automarker_model.json",
               {"model_id": MODEL_ID, "revision": info.sha, "backend": "onnxruntime-cpu"})
    LOG.info("Model provisioned at %s", directory)


class MathOCR:
    def __init__(self, directory: Path):
        if not directory.is_dir() or not (directory / "config.json").is_file():
            raise ValueError(f"Local model missing at {directory}. Run download-model first.")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from optimum.onnxruntime import ORTModelForVision2Seq
        from transformers import AutoImageProcessor, AutoTokenizer, TrOCRProcessor

        directory = directory.resolve()
        LOG.info("Loading local math OCR model from %s", directory)
        self.processor = TrOCRProcessor(
            image_processor=AutoImageProcessor.from_pretrained(
                str(directory), local_files_only=True, use_fast=False
            ),
            tokenizer=AutoTokenizer.from_pretrained(
                str(directory), local_files_only=True, use_fast=True
            ),
        )
        self.model = ORTModelForVision2Seq.from_pretrained(
            str(directory), local_files_only=True, provider="CPUExecutionProvider",
            use_cache=False, use_io_binding=False,
        )

    def recognize(self, path: Path, max_tokens: int = 256) -> dict:
        import torch
        from PIL import Image

        with Image.open(path) as original:
            image = original.convert("RGB")
        pixels = self.processor(images=image, return_tensors="pt").pixel_values
        with torch.inference_mode():
            tokens = self.model.generate(pixels, max_new_tokens=max_tokens, num_beams=1)
        latex = self.processor.batch_decode(tokens, skip_special_tokens=True)[0].strip()
        truncated = tokens.shape[1] >= max_tokens + 1
        LOG.debug("OCR %s -> %r (truncated=%s)", path, latex, truncated)
        return {"latex": latex, "truncated": truncated, "needs_review": True}


def recognize_extraction(extraction_path: Path, model_path: Path, variant: str = "normalized",
                         max_tokens: int = 256, engine: MathOCR | None = None) -> dict:
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    extraction = read_json(extraction_path)
    ocr = engine if engine is not None else MathOCR(model_path)
    for answer in extraction["answers"]:
        image = extraction_path.parent / answer["files"][variant]
        answer["ocr"] = ocr.recognize(image, max_tokens)
    manifest = model_path / "automarker_model.json"
    extraction["ocr_model"] = read_json(manifest) if manifest.exists() else {"path": str(model_path)}
    write_json(extraction_path.parent / "recognition.json", extraction)
    return extraction
