import pytest

from automarker.tex import dimension_pt, parse_boxes


def test_dimensions_and_reading_order(tmp_path):
    tex = tmp_path / "quiz.tex"
    widths = [3, 3, 5, 5, 8, 8, 3, 3, 5, 5, 8, 8, 8]
    tex.write_text("\n".join(
        rf"\begin{{tcolorbox}}[width={width}cm,height=0.9cm]\end{{tcolorbox}}"
        for width in widths), encoding="utf-8")
    boxes = parse_boxes(tex)
    assert len(boxes) == 13
    assert [round(b["width_pt"] * 2.54 / 72) for b in boxes] == widths
    assert all(b["height_pt"] == pytest.approx(0.9 * 72 / 2.54) for b in boxes)


def test_comments_nonempty_boxes_and_unsupported_dimensions(tmp_path):
    tex = tmp_path / "quiz.tex"
    tex.write_text(r"""
% \begin{tcolorbox}[width=99cm,height=99cm]\end{tcolorbox}
\begin{tcolorbox}[width=3cm,height=1cm]Instructions\end{tcolorbox}
\begin{tcolorbox}[width=3cm, % width comment
height=1cm]\end{tcolorbox}
""", encoding="utf-8")
    assert len(parse_boxes(tex)) == 1
    with pytest.raises(ValueError, match="literal TeX dimension"):
        dimension_pt(r"0.5\textwidth")


def test_tex_points_are_not_pdf_points():
    assert dimension_pt("72.27pt") == pytest.approx(72)
    assert dimension_pt("1in") == 72
