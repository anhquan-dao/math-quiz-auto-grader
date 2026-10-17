"""Batch extraction and optional OCR with one model load per run."""

import logging
from pathlib import Path

from .io import write_json
from .pipeline import extract_capture

LOG = logging.getLogger(__name__)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


def collect_images(inputs: list[Path]) -> list[Path]:
    paths = []
    for item in inputs:
        paths.extend(sorted(p for p in item.iterdir() if p.is_file() and
                            p.suffix.lower() in IMAGE_SUFFIXES) if item.is_dir() else [item])
    if not paths:
        raise ValueError("No input images found")
    if len({p.stem.casefold() for p in paths}) != len(paths):
        raise ValueError("Input image stems must be unique to avoid overwriting outputs")
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Input image does not exist: {path}")
    return paths


def process_captures(paths: list[Path], template: dict, output: Path,
                     page: int = 1, inset_mm: float = 1.5,
                     model: Path | None = None, variant: str = "normalized",
                     max_tokens: int = 256, key: dict | None = None) -> dict:
    engine = None
    if model is not None:
        from .ocr import MathOCR
        engine = MathOCR(model)
    summary = {"successful": [], "failed": []}
    for path in paths:
        capture_output = output / path.stem
        stage = "extract"
        try:
            extract_capture(path, template, capture_output, page, inset_mm)
            # New crops invalidate recognition and comparisons from an earlier run.
            for filename in ("recognition.json", "comparison.json"):
                (capture_output / filename).unlink(missing_ok=True)
            if engine is not None:
                from .ocr import recognize_extraction
                stage = "recognize"
                recognition = recognize_extraction(capture_output / "extraction.json", model,
                                                    variant, max_tokens, engine=engine)
                if key is not None:
                    from .grading import compare_answers
                    stage = "compare"
                    write_json(capture_output / "comparison.json", compare_answers(recognition, key))
            # A successful rerun should not retain an obsolete failure report.
            (capture_output / "failure.json").unlink(missing_ok=True)
            summary["successful"].append(str(path))
        except Exception as exc:
            LOG.exception("Failed capture %s during %s", path, stage)
            failure = {"input": str(path), "stage": stage, "error": str(exc)}
            summary["failed"].append(failure)
            write_json(capture_output / "failure.json", failure)
    write_json(output / "summary.json", summary)
    LOG.info("Batch complete: %d successful, %d failed", len(summary["successful"]),
             len(summary["failed"]))
    return summary
