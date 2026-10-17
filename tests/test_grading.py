from automarker.grading import compare_answers


def test_numeric_tolerance_and_unkeyed_answers():
    recognition = {"answers": [{"id": "a", "ocr": {"latex": "1.23451"}},
                                {"id": "b", "ocr": {"latex": "x"}}]}
    key = {"answers": {"a": {"mode": "numeric", "value": "1.2345", "tolerance": "0.00005"}}}
    result = compare_answers(recognition, key)
    assert [r["comparison"] for r in result["answers"]] == ["match", "unkeyed"]
    assert result["final_score"] is None
    assert all(r["needs_review"] for r in result["answers"])


def test_truncated_and_nonfinite_values_cannot_match():
    for value, truncated in [("NaN", False), ("Infinity", False), ("2", True), ("", False)]:
        result = compare_answers({"answers": [{"id": "a", "ocr": {"latex": value,
                                  "truncated": truncated}}]},
                                 {"answers": {"a": {"mode": "numeric", "value": "2"}}})
        assert result["answers"][0]["comparison"] == "no_match"
