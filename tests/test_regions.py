import cv2
import numpy as np
import pytest

from automarker.io import read_image, write_image
from automarker.pipeline import extract_capture
from automarker.regions import refine_box, southern_mask


def frame():
    ink = np.zeros((200, 400), np.uint8)
    cv2.rectangle(ink, (55, 65), (345, 125), 255, 2)
    return ink


def test_template_is_a_prior_and_detection_follows_the_actual_frame():
    result = refine_box(frame(), [50, 60, 340, 120], radius=10)
    assert result['detected']
    assert np.max(np.abs(np.array(result['bbox_px']) - [55, 65, 345, 125])) <= 2
    assert result['confidence'] > .85


def test_no_frame_or_out_of_search_frame_falls_back_without_following_handwriting():
    prior = [50, 60, 340, 120]
    ink = np.zeros((200, 400), np.uint8)
    cv2.putText(ink, 'x + y = 1', (75, 110), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 2)
    for image in (ink, frame()):
        result = refine_box(image, prior, radius=1)
        assert not result['detected']
        assert result['bbox_px'] == prior
        assert not result['edges']


@pytest.mark.parametrize('diagonal', [False, True])
def test_south_border_mask_removes_line_but_keeps_crossing_descender(diagonal):
    ink = frame()
    start, end = ((160, 105), (170, 145)) if diagonal else ((160, 105), (160, 145))
    cv2.line(ink, start, end, 255, 3)
    bounds = [58, 68, 342, 150]
    mask = southern_mask(ink, [55, 125, 345, 125], bounds, dpi=200)
    original = ink[68:150, 58:342]
    cleaned = original.copy()
    cleaned[mask > 0] = 0
    assert np.count_nonzero(cleaned[54:61, 15:80]) < 5  # Printed lower edge removed.
    expected = np.zeros_like(ink)
    cv2.line(expected, start, end, 255, 3)
    crossing = expected[68:150, 58:342] > 0
    assert np.array_equal(cleaned[crossing], original[crossing])
    assert np.array_equal(cleaned[65:], original[65:])  # Below-border writing untouched.


def test_south_mask_follows_a_sloped_edge_and_preserves_unrelated_ink():
    ink = np.zeros((200, 400), np.uint8)
    cv2.line(ink, (50, 120), (350, 129), 255, 2)
    cv2.line(ink, (160, 105), (165, 145), 255, 3)
    cv2.line(ink, (80, 90), (120, 90), 255, 2)  # Minus sign well above border.
    mask = southern_mask(ink, [50, 120, 350, 129], [50, 70, 350, 155], dpi=200)
    cleaned = ink[70:155, 50:350].copy()
    cleaned[mask > 0] = 0
    assert np.count_nonzero(cleaned[47:65, 5:75]) < 5
    assert np.array_equal(cleaned[:40], ink[70:110, 50:350])


@pytest.mark.parametrize('line_y', [10, 180])
def test_mask_outside_the_crop_never_erases_crop_content(line_y):
    mask = southern_mask(frame(), [50, line_y, 350, line_y], [50, 70, 350, 155], dpi=200)
    assert not mask.any()


def test_refinement_accepts_a_slightly_sloped_complete_frame():
    ink = np.zeros((200, 400), np.uint8)
    cv2.polylines(ink, [np.array([[50, 60], [340, 68], [340, 128], [50, 120]])], True, 255, 2)
    result = refine_box(ink, [50, 64, 340, 124], radius=10)
    assert result['detected']
    assert abs(result['bbox_px'][1]-64) < 3
    assert abs(result['bbox_px'][3]-124) < 3


def test_nearby_box_edge_is_not_preferred_to_the_expected_edge():
    ink = np.zeros((200, 430), np.uint8)
    cv2.rectangle(ink, (20, 60), (200, 120), 255, 2)
    cv2.rectangle(ink, (210, 60), (390, 120), 255, 2)
    result = refine_box(ink, [212, 60, 392, 120], radius=16)
    assert result['detected']
    assert abs(result['bbox_px'][0]-210) <= 2


def test_adjacent_row_top_is_not_mistaken_for_the_shifted_box_bottom():
    ink = np.zeros((240, 400), np.uint8)
    cv2.rectangle(ink, (50, 60), (340, 120), 255, 2)
    cv2.rectangle(ink, (50, 137), (340, 197), 255, 2)
    result = refine_box(ink, [50, 70, 340, 130], radius=16)
    assert result['detected']
    assert abs(result['bbox_px'][1]-60) <= 2
    assert abs(result['bbox_px'][3]-120) <= 2


@pytest.mark.parametrize('keep', [False, True])
def test_pipeline_expands_and_caps_crops_and_retains_unmasked_evidence(tmp_path, monkeypatch, keep):
    from automarker import pipeline

    ink = frame()
    cv2.line(ink, (160, 105), (160, 145), 255, 3)
    cv2.rectangle(ink, (55, 153), (345, 188), 255, 2)
    image = cv2.cvtColor(255-ink, cv2.COLOR_GRAY2BGR)
    source = tmp_path / 'phone.png'
    write_image(source, image)
    monkeypatch.setattr(pipeline, 'align', lambda *args: (image, {}, {}))
    monkeypatch.setattr(pipeline, 'marker_overlay', lambda source, markers: source)
    monkeypatch.setattr(pipeline, 'normalize_light', lambda source: cv2.cvtColor(source, cv2.COLOR_BGR2GRAY))
    template = {'schema_version': 1, 'dpi': 200, 'dictionary': 'DICT_4X4_1000',
                'pages': [{'page': 1, 'boxes': [
                    {'id': 'a', 'bbox_px': [50, 60, 340, 120]},
                    {'id': 'b', 'bbox_px': [50, 148, 340, 183]}]}]}
    output = tmp_path / 'capture'
    result = extract_capture(source, template, output, south_mm=10, keep_south_border=keep)
    first, second = result['answers']
    assert first['frame']['detected'] and second['frame']['detected']
    assert first['neighbor_limited']
    assert first['bbox_px'][3] == second['frame']['bbox_px'][1]-2
    assert second['bbox_px'][3] == image.shape[0]  # Page boundary limits expansion.
    assert second['expansion_limited']
    assert (first['border_removed_pixels'] == 0) == keep
    raw = read_image(output / first['files']['raw'])
    crop = read_image(output / first['files']['normalized'])
    before = read_image(output / first['files']['normalized_unmasked'])
    mask = read_image(output / first['files']['border_mask'])
    assert crop.shape == raw.shape == before.shape == mask.shape
    assert (output / '09_crop_areas.png').exists() and (output / '10_border_mask.png').exists()
    assert np.array_equal(crop[mask > 0], np.full_like(crop[mask > 0], 255))
    assert np.array_equal(crop[mask == 0], before[mask == 0])


@pytest.mark.parametrize('option', [{'inset_mm': -1}, {'south_mm': float('nan')},
                                   {'box_search_mm': float('inf')}])
def test_invalid_crop_distances_fail_before_image_processing(tmp_path, option):
    template = {'schema_version': 1, 'pages': [{'page': 1}]}
    with pytest.raises(ValueError, match='finite and nonnegative'):
        extract_capture(tmp_path / 'missing.png', template, tmp_path, **option)
