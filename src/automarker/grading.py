"""Conservative answer-key comparison; unconfirmed OCR always requires review."""

import logging
import re
from decimal import Decimal, InvalidOperation

LOG = logging.getLogger(__name__)


def normalize_latex(text: str) -> str:
    return re.sub(r"\s+", "", text.strip().strip("$"))


def compare_answers(recognition: dict, key: dict) -> dict:
    results = []
    for answer in recognition["answers"]:
        expected = key.get("answers", {}).get(answer["id"])
        ocr = answer.get("ocr", {})
        observed = ocr.get("latex", "")
        matched = False
        if expected is not None and observed and not ocr.get("truncated", False):
            mode = expected.get("mode", "exact")
            if mode == "exact":
                matched = normalize_latex(observed) == normalize_latex(expected["value"])
            elif mode == "numeric":
                try:
                    actual, target = Decimal(observed), Decimal(expected["value"])
                    tolerance = Decimal(str(expected.get("tolerance", "0")))
                    if not tolerance.is_finite() or tolerance < 0:
                        raise ValueError("Numeric tolerance must be finite and nonnegative")
                    matched = actual.is_finite() and target.is_finite() and abs(actual-target) <= tolerance
                except InvalidOperation:
                    matched = False
            else:
                raise ValueError(f"Unsupported grading mode {mode!r}")
        results.append({"id": answer["id"], "observed": observed,
                        "comparison": "unkeyed" if expected is None else
                                      "match" if matched else "no_match",
                        "needs_review": True})
    LOG.info("Compared %d answers; OCR-derived results require human review", len(results))
    return {"answers": results, "final_score": None,
            "note": "Candidate comparisons only; confirm OCR before assigning grades."}
