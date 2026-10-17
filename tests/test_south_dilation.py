import cv2
import numpy as np
import pytest

from automarker.regions import (
    estimate_southern_band,
    estimate_southern_band_edges,
    southern_dilate,
    southern_mask,
)


def sample():
    ink = np.zeros((120, 260), np.uint8)
    cv2.line(ink, (10, 65), (250, 65), 255, 2)
    cv2.line(ink, (100, 40), (100, 90), 255, 2)
    cv2.line(ink, (160, 25), (185, 25), 255, 2)
    return ink, [10, 65, 250, 65], [15, 15, 245, 105]


def test_full_band_is_erased_and_vertical_dilation_reconnects_the_crossing():
    ink, line, bounds = sample()
    before = ink.copy()
    result = southern_dilate(ink, line, bounds, 200)
    band, _, _, _ = estimate_southern_band_edges(ink, line, bounds, 200)
    assert np.array_equal(band, result['band_mask'])
    assert not result['masked_ink'][band > 0].any()
    assert result['kernel_height_px'] == result['band_height_px']+2
    assert result['recovered_ink'][65-15, 100-15] == 255
    assert result['recovered_ink'][65-15, 40-15] == 0  # Frame-only region stays erased.
    original = ink[15:105, 15:245]
    assert np.array_equal(result['recovered_ink'][result['strip_mask'] == 0],
                          original[result['strip_mask'] == 0])
    assert np.array_equal(ink, before)
    assert not np.any(result['restored_mask'][result['strip_mask'] == 0])
    assert result['restored_mask'].any()
    assert not result['new_ink_mask'].any()
    assert np.all(result['recovered_ink'] <= original)


def test_exact_band_sized_centered_kernel_leaves_a_one_pixel_gap():
    ink, line, bounds = sample()
    _, _, half, _ = estimate_southern_band_edges(ink, line, bounds, 200)
    result = southern_dilate(ink, line, bounds, 200, dilation_height_px=2*half+1)
    assert result['recovered_ink'][65-15, 100-15] == 0
    assert result['restored_mask'].any()


@pytest.mark.parametrize('outside', [False, True])
def test_no_ink_is_created_on_blank_images_or_when_the_border_is_outside_the_crop(outside):
    ink = np.zeros((100, 220), np.uint8)
    if outside:
        cv2.line(ink, (40, 20), (80, 20), 255, 2)
    result = southern_dilate(ink, [0, 180 if outside else 60, 219, 180 if outside else 60],
                             [0, 0, 220, 100], 200)
    assert np.array_equal(result['recovered_ink'], ink)
    assert not result['restored_mask'].any()


def test_bare_printed_border_is_removed_completely():
    ink = np.zeros((100, 220), np.uint8)
    cv2.line(ink, (0, 60), (219, 60), 255, 2)
    result = southern_dilate(ink, [0, 60, 219, 60], [0, 0, 220, 100], 200)
    assert not result['masked_ink'].any() and not result['recovered_ink'].any()


def test_dilation_only_selects_original_pixels_near_a_non_crossing_stroke():
    ink, line, bounds = sample()
    cv2.line(ink, (160, 55), (160, 59), 255, 1)
    result = southern_dilate(ink, line, bounds, 200)
    original = ink[15:105, 15:245]
    assert np.any((result['dilation_mask'] > 0) & (original == 0))
    assert not result['new_ink_mask'].any()
    assert np.all(result['recovered_ink'] <= original)
    expected = result['masked_ink'] | (original & result['dilation_mask'] & result['band_mask'])
    assert np.array_equal(result['recovered_ink'], expected)


@pytest.mark.parametrize('kernel', [0, -1, 2.5, True])
def test_invalid_vertical_kernel_is_rejected(kernel):
    ink, line, bounds = sample()
    with pytest.raises(ValueError, match='positive integer'):
        southern_dilate(ink, line, bounds, 200, dilation_height_px=kernel)


def test_sloped_band_follows_the_detected_line_and_covers_removed_border_pixels():
    ink, _, bounds = sample()
    ink[:] = 0
    line = [10, 60, 250, 68]
    cv2.line(ink, (10, 60), (250, 68), 255, 2)
    cv2.line(ink, (100, 40), (100, 90), 255, 2)
    result = southern_dilate(ink, line, bounds, 200)
    old_mask = southern_mask(ink, line, bounds, 200)
    assert not old_mask[result['band_mask'] == 0].any()
    assert not result['masked_ink'][result['band_mask'] > 0].any()
    rows, columns = np.nonzero(result['band_mask'])
    assert rows[columns == columns.max()].mean() > rows[columns == columns.min()].mean()
    assert not result['new_ink_mask'].any()


def test_edge_portions_ignore_dense_central_writing_and_use_both_sides():
    ink = np.zeros((100, 301), np.uint8)
    ink[59:62, :] = 255  # Three-pixel border on the left.
    ink[58:63, 225:271] = 255  # Five-pixel border on the right.
    ink[50:71, 80:221] = 255  # Dense central handwriting must not affect the estimate.
    line, bounds = [0, 60, 300, 60], [10, 10, 291, 90]
    _, _, half, estimate = estimate_southern_band_edges(ink, line, bounds, 200)
    left, right = estimate['portions']
    assert left['x_range_px'] == [30, 75] and left['mean_thickness_px'] == 3
    assert right['x_range_px'] == [225, 270] and right['mean_thickness_px'] == 5
    assert left['samples'] == right['samples'] == 45
    assert estimate['estimated_thickness_px'] == 5 and not estimate['fallback']
    assert half == 4
    _, _, old_half = estimate_southern_band(ink, line, bounds, 200)
    assert old_half > half  # Original production median remains a separate estimate.


def test_edge_estimate_averages_runs_and_excludes_unbounded_crossings():
    ink = np.zeros((100, 301), np.uint8)
    ink[59:62, :] = 255
    ink[58:63, 30:50] = 255
    ink[45:76, 50:55] = 255
    _, _, _, estimate = estimate_southern_band_edges(ink, [0, 60, 300, 60], [0, 0, 301, 100], 200)
    left = estimate['portions'][0]
    assert left['samples'] == 40
    assert left['mean_thickness_px'] == 4  # Mean of twenty 5px and twenty 3px runs.
    assert estimate['estimated_thickness_px'] == 4


def test_missing_edge_samples_use_other_side_then_explicit_fallback():
    ink = np.zeros((100, 301), np.uint8)
    ink[59:62, 225:270] = 255
    _, _, _, estimate = estimate_southern_band_edges(ink, [0, 60, 300, 60], [0, 0, 301, 100], 200)
    assert estimate['portions'][0]['samples'] == 0
    assert estimate['estimated_thickness_px'] == 3 and not estimate['fallback']
    ink[:] = 0
    _, _, _, estimate = estimate_southern_band_edges(ink, [0, 60, 300, 60], [0, 0, 301, 100], 200)
    assert estimate['estimated_thickness_px'] == 1 and estimate['fallback']


def test_two_sided_dilation_fills_a_gap_but_rejects_outer_rims():
    ink, line, bounds = sample()
    cv2.line(ink, (103, 40), (103, 90), 255, 1)  # One-column gap at x=102.
    vertical_only = southern_dilate(ink, line, bounds, 200, horizontal_dilation_width_px=1)
    result = southern_dilate(ink, line, bounds, 200, horizontal_dilation_width_px=3)
    assert result['horizontal_dilation_width_px'] == 3
    assert np.array_equal(vertical_only['dilation_mask'], result['vertical_dilation_mask'])
    row = 65-bounds[1]
    assert vertical_only['recovered_ink'][row, 102-bounds[0]] == 0
    assert result['recovered_ink'][row, 102-bounds[0]] == 255
    for x in (98, 104):
        assert result['horizontal_union_mask'][row, x-bounds[0]] == 255
        assert result['dilation_mask'][row, x-bounds[0]] == 0
        assert result['recovered_ink'][row, x-bounds[0]] == 0
    assert result['horizontal_dilation_sum'].dtype == np.uint16
    assert result['horizontal_dilation_sum'].max() == 510  # Sum must not wrap or saturate.
    assert result['horizontal_sum_threshold'] == 255
    assert np.array_equal(result['dilation_mask'] > 0, result['horizontal_dilation_sum'] > 255)
    assert np.count_nonzero(result['restored_mask']) > np.count_nonzero(vertical_only['restored_mask'])
    original = ink[15:105, 15:245]
    assert np.all(result['recovered_ink'] <= original)
    assert not result['new_ink_mask'].any()
    assert np.array_equal(result['recovered_ink'][result['band_mask'] == 0],
                          original[result['band_mask'] == 0])


def test_isolated_vertical_crossing_has_no_horizontal_rims():
    ink, line, bounds = sample()
    result = southern_dilate(ink, line, bounds, 200)
    assert np.array_equal(result['recovered_ink'], result['vertical_recovered_ink'])
    assert np.array_equal(result['dilation_mask'], result['vertical_dilation_mask'])
    assert np.count_nonzero(result['horizontal_union_mask']) > np.count_nonzero(result['dilation_mask'])


def test_default_wider_dilation_recovers_more_of_an_eight_shaped_loop():
    ink = np.zeros((120, 260), np.uint8)
    cv2.line(ink, (10, 65), (250, 65), 255, 2)
    cv2.ellipse(ink, (100, 44), (6, 6), 0, 0, 360, 255, 1)
    cv2.ellipse(ink, (100, 57), (7, 8), 0, 0, 360, 255, 1)
    line, bounds = [10, 65, 250, 65], [15, 15, 245, 105]
    narrow = southern_dilate(ink, line, bounds, 200, horizontal_dilation_width_px=3)
    result = southern_dilate(ink, line, bounds, 200)
    assert result['horizontal_dilation_width_px'] == 15
    # Changing recovery reach must not enlarge the removal band or the vertical mask.
    assert np.array_equal(result['band_mask'], narrow['band_mask'])
    assert np.array_equal(result['vertical_dilation_mask'], narrow['vertical_dilation_mask'])
    assert cv2.countNonZero(result['restored_mask']) > cv2.countNonZero(narrow['restored_mask'])
    # Count recovery of actual loop pixels, independently of the overlapping printed line.
    loop = np.zeros_like(ink)
    cv2.ellipse(loop, (100, 57), (7, 8), 0, 0, 360, 255, 1)
    loop = loop[15:105, 15:245]
    assert cv2.countNonZero(result['restored_mask'] & loop) > cv2.countNonZero(narrow['restored_mask'] & loop)
    assert not result['new_ink_mask'].any()
    assert not result['dilation_mask'][result['strip_mask'] == 0].any()
    assert np.array_equal(result['dilation_mask'] > 0, result['horizontal_dilation_sum'] > 255)
    assert not result['recovered_ink'][65-15, 40-15]  # A remote bare-border section stays erased.


def test_vertical_only_result_restores_original_ink_and_preserves_outside_band():
    ink, line, bounds = sample()
    result = southern_dilate(ink, line, bounds, 200)
    original = ink[15:105, 15:245]
    expected = result['masked_ink'] | (original & result['vertical_dilation_mask'] & result['band_mask'])
    assert np.array_equal(result['vertical_recovered_ink'], expected)
    assert np.all(result['vertical_recovered_ink'] <= original)
    assert np.array_equal(result['vertical_recovered_ink'][result['band_mask'] == 0],
                          original[result['band_mask'] == 0])


@pytest.mark.parametrize('width', [0, -1, 2.5, True])
def test_invalid_horizontal_kernel_is_rejected(width):
    ink, line, bounds = sample()
    with pytest.raises(ValueError, match='Horizontal dilation width must be a positive integer'):
        southern_dilate(ink, line, bounds, 200, horizontal_dilation_width_px=width)


@pytest.mark.parametrize('kernel', [3, 15])
def test_strip_extends_seven_pixels_per_side_independently_of_dilation_height(kernel):
    ink, line, bounds = sample()
    result = southern_dilate(ink, line, bounds, 200, dilation_height_px=kernel)
    column = 100-bounds[0]
    band_rows = np.flatnonzero(result['band_mask'][:, column])
    strip_rows = np.flatnonzero(result['strip_mask'][:, column])
    assert strip_rows[0] == band_rows[0]-7
    assert strip_rows[-1] == band_rows[-1]+7
    assert len(strip_rows) == len(band_rows)+14
    assert not result['dilation_mask'][result['strip_mask'] == 0].any()


@pytest.mark.parametrize('padding', [-1, 2.5, True])
def test_invalid_strip_padding_is_rejected(padding):
    ink, line, bounds = sample()
    with pytest.raises(ValueError, match='nonnegative integer'):
        southern_dilate(ink, line, bounds, 200, strip_padding_px=padding)
