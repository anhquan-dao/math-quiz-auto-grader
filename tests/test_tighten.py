import cv2
import numpy as np
import pytest

from automarker.regions import horizontal_bounds


def test_horizontal_bounds_keep_small_marks_and_padding_and_do_not_modify_binary():
    binary = np.full((80, 240), 255, np.uint8)
    binary[30:50, 90:140] = 0
    binary[40, 60] = 0  # Small independent dot must survive.
    binary[55, 155:160] = 0  # Isolated minus sign.
    before = binary.copy()
    assert horizontal_bounds(binary, 4) == (56, 164)
    assert np.array_equal(binary, before)


def test_blank_and_edge_touching_ink_are_not_cut_and_padding_does_not_expand():
    binary = np.full((50, 100), 255, np.uint8)
    assert horizontal_bounds(binary, 3) == (0, 100)
    binary[10:30, :2] = 0
    binary[15:20, -2:] = 0
    assert horizontal_bounds(binary, 0) == (0, 100)
    binary[:, :] = 255
    binary[20, 50] = 0
    assert horizontal_bounds(binary, 200) == (0, 100)


def framed_crop():
    binary = np.full((100, 220), 255, np.uint8)
    cv2.rectangle(binary, (5, 5), (215, 75), 0, 1)
    frame = {'detected': True, 'bbox_px': [5, 5, 215, 75], 'edges': {
        'north': [5, 5, 215, 5], 'south': [5, 75, 215, 75],
        'west': [5, 5, 5, 75], 'east': [215, 5, 215, 75]}}
    return binary, frame


def test_frame_is_excluded_from_measurement_but_descenders_and_corner_marks_remain():
    binary, frame = framed_crop()
    binary[30:50, 90:130] = 0
    binary[80:90, 145:148] = 0  # Below-border content remains part of horizontal bounds.
    assert horizontal_bounds(binary, 2, frame=frame) == (88, 150)
    binary[10, 12] = 0  # Disconnected mark inside a corner search zone.
    assert horizontal_bounds(binary, 2, frame=frame) == (10, 150)


def test_blank_frame_keeps_full_width_and_unconfirmed_frame_is_not_discarded():
    binary, frame = framed_crop()
    assert horizontal_bounds(binary, 2, frame=frame) == (0, 220)
    frame['detected'] = False
    assert horizontal_bounds(binary, 2, frame=frame) == (3, 218)


def test_cropped_rounded_frame_fragments_do_not_prevent_tightening():
    binary = np.full((100, 220), 255, np.uint8)
    for start, stop in [((17, 5), (203, 5)), ((17, 75), (203, 75)),
                        ((5, 17), (5, 63)), ((215, 17), (215, 63))]:
        cv2.line(binary, start, stop, 0, 2)
    for center, start, stop in [((17, 17), 180, 270), ((203, 17), 270, 360),
                                ((17, 63), 90, 180), ((203, 63), 0, 90)]:
        cv2.ellipse(binary, center, (12, 12), 0, start, stop, 0, 2)
    binary[35:50, 90:130] = 0
    binary[80:90, 145:148] = 0
    _, frame = framed_crop()
    frame['edges'] = {'north': [17, 5, 203, 5], 'south': [17, 75, 203, 75],
                      'west': [5, 17, 5, 63], 'east': [215, 17, 215, 63]}
    crop = binary[7:95, 7:213]
    assert horizontal_bounds(crop, 2, frame=frame, origin=(7, 7)) == (81, 143)


@pytest.mark.parametrize('padding', [-1, float('nan'), float('inf')])
def test_invalid_tightening_padding_fails_before_reading_images(tmp_path, padding):
    from automarker.pipeline import extract_capture

    template = {'schema_version': 1, 'pages': [{'page': 1}]}
    with pytest.raises(ValueError, match='finite and nonnegative'):
        extract_capture(tmp_path/'missing.jpg', template, tmp_path, tighten_padding_mm=padding)


@pytest.mark.parametrize('amount', [-1, float('nan'), float('inf')])
def test_invalid_static_cut_fails_before_reading_images(tmp_path, amount):
    from automarker.pipeline import extract_capture

    template = {'schema_version': 1, 'pages': [{'page': 1}]}
    with pytest.raises(ValueError, match='finite and nonnegative'):
        extract_capture(tmp_path/'missing.jpg', template, tmp_path, static_tighten_mm=amount)


def test_invalid_tightening_mode_fails_before_reading_images(tmp_path):
    from automarker.pipeline import extract_capture

    template = {'schema_version': 1, 'pages': [{'page': 1}]}
    with pytest.raises(ValueError, match='Tighten mode must be static, dynamic, or both'):
        extract_capture(tmp_path/'missing.jpg', template, tmp_path, tighten_mode='unknown')
