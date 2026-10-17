from pathlib import Path

import cv2
import numpy as np
import pytest

from automarker import pipeline
from automarker.io import write_image
from automarker.ocr import recognize_extraction
from automarker.report import build_archive


@pytest.fixture
def capture(tmp_path, monkeypatch):
    image = np.full((180, 360, 3), 255, np.uint8)
    cv2.rectangle(image, (40, 50), (320, 115), (0, 0, 0), 2)
    cv2.putText(image, 'x + 1', (100, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    source = tmp_path / 'phone.jpg'
    write_image(source, image)
    monkeypatch.setattr(pipeline, 'align', lambda *args: (image, {}, {}))
    monkeypatch.setattr(pipeline, 'marker_overlay', lambda source, markers: source)
    template = {'schema_version': 1, 'dpi': 200, 'dictionary': 'DICT_4X4_1000',
                'pages': [{'page': 1, 'boxes': [
                    {'id': 'answer_001', 'bbox_px': [40, 50, 320, 115]}]}]}
    output = tmp_path / 'capture'
    return source, template, output


@pytest.mark.parametrize('variant', ['normalized', 'raw', 'binary'])
def test_compact_output_retains_only_selected_and_binary_crops_and_builds_html(capture, variant):
    source, template, output = capture
    result = pipeline.extract_capture(source, template, output, variant=variant)
    files = result['answers'][0]['files']
    assert set(files) == {variant, 'binary'}
    expected = {'01_input.png', '02_binary.png', '03_boxes.png', 'extraction.json', *files.values()}
    assert {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()} == expected
    archive = output.parent / 'archive'
    build_archive(output, archive, demo_expected=True)
    assert 'data:image/png;base64,' in (archive/'phone.jpg.html').read_text(encoding='utf-8')


def test_rerun_removes_obsolete_generated_images_and_preserves_user_files(capture):
    source, template, output = capture
    debug = pipeline.extract_capture(source, template, output, debug_images=True)
    first = debug['answers'][0]
    original = (output/first['files']['normalized']).read_bytes()
    assert (output/'debug/10_border_mask.png').exists()
    write_image(output/'04_aligned.png', np.zeros((10, 10), np.uint8))
    write_image(output/'crops/answer_001_raw.png', np.zeros((10, 10), np.uint8))
    write_image(output/'my_annotation.png', np.zeros((10, 10), np.uint8))
    (output/'notes.csv').write_text('Keep my review notes', encoding='utf-8')
    compact = pipeline.extract_capture(source, template, output)
    assert not (output/'debug').exists()
    assert not (output/'04_aligned.png').exists()
    assert not (output/'crops/answer_001_raw.png').exists()
    assert (output/'notes.csv').read_text() == 'Keep my review notes'
    assert (output/'my_annotation.png').exists()
    assert (output/compact['answers'][0]['files']['normalized']).read_bytes() == original


def test_compact_ocr_reads_the_retained_crop_and_reports_missing_variants(capture):
    source, template, output = capture
    result = pipeline.extract_capture(source, template, output, variant='binary')
    calls = []

    class Engine:
        def recognize(self, path, max_tokens):
            assert path.is_file()
            calls.append(path)
            return {'latex': 'x+1'}

    engine = Engine()
    recognized = recognize_extraction(output/'extraction.json', Path('models/test'),
                                       variant='binary', engine=engine)
    assert calls == [output/result['answers'][0]['files']['binary']]
    assert recognized['ocr_variant'] == 'binary'
    with pytest.raises(ValueError, match='Re-extract with --variant raw'):
        recognize_extraction(output/'extraction.json', Path('models/test'), variant='raw', engine=engine)
    assert len(calls) == 1


def test_tightening_changes_only_horizontal_bounds_and_keeps_all_variants_aligned(capture):
    from automarker.io import read_image

    source, template, output = capture
    original = pipeline.extract_capture(source, template, output, debug_images=True, tighten_ew=False)
    before = original['answers'][0]
    originals = {name: read_image(output/path) for name, path in before['files'].items()}
    count = len([path for path in output.rglob('*') if path.is_file()])
    result = pipeline.extract_capture(source, template, output, tighten_ew=True,
                                      tighten_padding_mm=.5, debug_images=True)
    answer = result['answers'][0]
    x0, y0, x1, y1 = answer['bbox_px']
    old_x0, old_y0, old_x1, old_y1 = before['bbox_px']
    assert (y0, y1) == (old_y0, old_y1)
    assert old_x0 < x0 < x1 < old_x1
    assert answer['pre_tighten_bbox_px'] == before['bbox_px']
    assert answer['tighten_ew_px'] == {'west': x0-old_x0, 'east': old_x1-x1}
    for name, path in answer['files'].items():
        actual = read_image(output/path)
        assert actual.shape[:2] == (y1-y0, x1-x0)
        assert np.array_equal(actual, originals[name][:, x0-old_x0:x1-old_x0])
    assert len([path for path in output.rglob('*') if path.is_file()]) == count


def test_tightening_is_enabled_by_default_with_one_point_five_mm_padding(capture):
    source, template, output = capture
    full = pipeline.extract_capture(source, template, output, tighten_ew=False)['answers'][0]['bbox_px']
    result = pipeline.extract_capture(source, template, output)
    default = result['answers'][0]['bbox_px']
    assert result['crop_options']['tighten_ew'] is True
    assert result['crop_options']['tighten_padding_mm'] == 1.5
    assert result['crop_options']['tighten_mode'] == 'both'
    assert result['crop_options']['static_tighten_mm'] == 1.5
    assert result['crop_options']['south_border_method'] == 'bidirectional-recovery'
    assert result['crop_options']['horizontal_dilation_width_px'] == 15
    explicit = pipeline.extract_capture(source, template, output, tighten_ew=True,
                                         tighten_padding_mm=1.5)['answers'][0]['bbox_px']
    smaller = pipeline.extract_capture(source, template, output,
                                        tighten_padding_mm=.5)['answers'][0]['bbox_px']
    assert default == explicit
    assert full[0] < default[0] < default[2] < full[2]
    assert default[1::2] == full[1::2]
    assert default[0] == smaller[0]-8 and default[2] == smaller[2]+8  # 1 mm at 200 DPI.


def test_static_tightening_removes_fixed_edges_and_keeps_variants_as_exact_slices(capture):
    from automarker.io import read_image

    source, template, output = capture
    full = pipeline.extract_capture(source, template, output, tighten_ew=False, debug_images=True)
    before = full['answers'][0]
    images = {name: read_image(output/path) for name, path in before['files'].items()}
    count = sum(path.is_file() for path in output.rglob('*'))
    result = pipeline.extract_capture(source, template, output, tighten_mode='static', debug_images=True)
    answer = result['answers'][0]
    x0, y0, x1, y1 = before['bbox_px']
    assert answer['bbox_px'] == [x0+12, y0, x1-12, y1]
    assert answer['post_static_bbox_px'] == answer['bbox_px']
    assert answer['static_tighten_ew_px'] == {'west': 12, 'east': 12}
    assert answer['dynamic_tighten_ew_px'] == {'west': 0, 'east': 0}
    for name, path in answer['files'].items():
        assert np.array_equal(read_image(output/path), images[name][:, 12:-12])
    assert sum(path.is_file() for path in output.rglob('*')) == count


def test_both_runs_static_before_dynamic_so_discarded_edge_ink_does_not_set_content_bounds(capture):
    source, template, output = capture
    image = pipeline.align()[0]  # Fixture supplies an already aligned image.
    image[85:88, 45:48] = 0  # Foreground inside the strip the static stage must cut away.
    dynamic = pipeline.extract_capture(source, template, output, tighten_mode='dynamic',
                                        tighten_padding_mm=0)['answers'][0]
    static = pipeline.extract_capture(source, template, output, tighten_mode='static')['answers'][0]
    combined = pipeline.extract_capture(source, template, output, tighten_mode='both',
                                         tighten_padding_mm=0)['answers'][0]
    assert dynamic['static_tighten_ew_px'] == {'west': 0, 'east': 0}
    assert combined['post_static_bbox_px'] == static['bbox_px']
    assert dynamic['bbox_px'][0] < static['bbox_px'][0] < combined['bbox_px'][0]
    assert combined['bbox_px'][2] < static['bbox_px'][2]
    assert combined['dynamic_tighten_ew_px']['west'] > 0
    assert combined['dynamic_tighten_ew_px']['east'] > 0


def test_static_zero_is_a_noop_and_disabling_tightening_disables_both_stages(capture):
    source, template, output = capture
    full = pipeline.extract_capture(source, template, output, tighten_ew=False)['answers'][0]
    zero = pipeline.extract_capture(source, template, output, tighten_mode='static',
                                     static_tighten_mm=0)['answers'][0]
    assert zero['bbox_px'] == full['bbox_px']
    assert full['static_tighten_ew_px'] == full['dynamic_tighten_ew_px'] == {'west': 0, 'east': 0}
    dynamic = pipeline.extract_capture(source, template, output, tighten_mode='dynamic')['answers'][0]
    both_zero = pipeline.extract_capture(source, template, output, tighten_mode='both',
                                          static_tighten_mm=0)['answers'][0]
    assert both_zero['bbox_px'] == dynamic['bbox_px']


def test_static_cut_cannot_empty_a_crop(capture):
    source, template, output = capture
    with pytest.raises(ValueError, match='Static tightening would empty answer_001'):
        pipeline.extract_capture(source, template, output, tighten_mode='static', static_tighten_mm=30)


@pytest.mark.parametrize('keep_border', [False, True])
@pytest.mark.parametrize('method', ['bidirectional-recovery', 'protected-crossings'])
def test_normalized_crop_marks_only_removed_south_pixels_red(capture, keep_border, method):
    from automarker.io import read_image

    source, template, output = capture
    image = pipeline.align()[0]
    cv2.line(image, (160, 100), (165, 130), (0, 0, 0), 2)
    result = pipeline.extract_capture(source, template, output, keep_south_border=keep_border,
                                      debug_images=True, south_border_method=method)
    answer = result['answers'][0]
    normalized = read_image(output/answer['files']['normalized'])
    unmasked = read_image(output/answer['files']['normalized_unmasked'])
    mask = read_image(output/answer['files']['border_mask'])[:, :, 0] > 0
    red = np.all(normalized == (0, 0, 255), axis=2)
    assert np.array_equal(red, mask)
    assert np.array_equal(normalized[~red], unmasked[~red])
    assert bool(red.any()) is (not keep_border)
    assert bool(answer['normalized_overlay']) is (not keep_border)
    assert answer['south_border']['method'] == method
    assert answer['south_border']['applied'] is (not keep_border)
    if not keep_border:
        archive = output.parent/'archive'
        build_archive(output, archive, demo_expected=True)
        assert 'Red: removed south-border pixels. OCR uses a clean copy.' in (
            archive/'phone.jpg.html').read_text(encoding='utf-8')


@pytest.mark.parametrize('failure', [False, True])
def test_ocr_gets_clean_pixels_and_temporary_inputs_are_removed(capture, failure):
    from automarker.io import read_image

    source, template, output = capture
    extraction = pipeline.extract_capture(source, template, output)
    preview_path = output/extraction['answers'][0]['files']['normalized']
    preview_bytes = preview_path.read_bytes()
    expected = read_image(preview_path)
    red = np.all(expected == (0, 0, 255), axis=2)
    assert red.any()
    expected[red] = 255
    calls = []

    class Engine:
        def recognize(self, path, max_tokens):
            calls.append(path)
            assert path != preview_path
            assert np.array_equal(read_image(path), expected)
            if failure:
                raise RuntimeError('Simulated OCR failure')
            return {'latex': 'x+1'}

    if failure:
        with pytest.raises(RuntimeError, match='Simulated OCR failure'):
            recognize_extraction(output/'extraction.json', Path('models/test'), engine=Engine())
    else:
        recognize_extraction(output/'extraction.json', Path('models/test'), engine=Engine())
    assert len(calls) == 1 and not calls[0].exists()
    assert not list(output.glob('.ocr-clean-*'))
    assert preview_path.read_bytes() == preview_bytes


@pytest.mark.parametrize('method', ['bidirectional-recovery', 'protected-crossings'])
def test_pipeline_applies_selected_method_before_tightening(capture, method):
    from automarker.io import read_image
    from automarker.regions import southern_dilate, southern_mask

    source, template, output = capture
    image = pipeline.align()[0]
    cv2.ellipse(image, (160, 94), (6, 6), 0, 0, 360, (0, 0, 0), 1)
    cv2.ellipse(image, (160, 107), (7, 8), 0, 0, 360, (0, 0, 0), 1)
    result = pipeline.extract_capture(source, template, output, south_border_method=method,
                                      horizontal_dilation_width_px=9, debug_images=True)
    answer = result['answers'][0]
    assert answer['frame']['detected']
    ink = 255-read_image(output/'02_binary.png')[:, :, 0]
    line, bounds = answer['frame']['edges']['south'], answer['pre_tighten_bbox_px']
    if method == 'bidirectional-recovery':
        recovered = southern_dilate(ink, line, bounds, template['dpi'], horizontal_dilation_width_px=9)
        expected = recovered['removed_mask']
        assert answer['south_border']['horizontal_dilation_width_px'] == 9
        assert answer['south_border']['thickness_estimate']['method'] == 'edge_portions'
    else:
        expected = southern_mask(ink, line, bounds, template['dpi'])
    x0, y0, x1, y1 = answer['bbox_px']
    expected = expected[:, x0-bounds[0]:x1-bounds[0]]
    actual = read_image(output/answer['files']['border_mask'])[:, :, 0]
    assert np.array_equal(actual, expected)
    original = (255-ink)[y0:y1, x0:x1].copy()
    original[expected > 0] = 255
    assert np.array_equal(read_image(output/answer['files']['binary'])[:, :, 0], original)
    assert answer['border_removed_pixels'] == cv2.countNonZero(expected)


@pytest.mark.parametrize('method', ['bidirectional-recovery', 'protected-crossings'])
def test_uncertain_frame_skips_both_removal_methods(capture, method):
    source, template, output = capture
    result = pipeline.extract_capture(source, template, output, box_mode='template', south_border_method=method)
    answer = result['answers'][0]
    assert answer['south_border'] == {'method': method, 'applied': False}
    assert answer['border_removed_pixels'] == 0


@pytest.mark.parametrize('options', [
    {'south_border_method': 'unknown'}, {'horizontal_dilation_width_px': 0},
    {'horizontal_dilation_width_px': -1}, {'horizontal_dilation_width_px': 1.5},
    {'horizontal_dilation_width_px': True},
])
def test_invalid_border_options_fail_before_writing(capture, options):
    source, template, output = capture
    with pytest.raises(ValueError):
        pipeline.extract_capture(source, template, output, **options)
    assert not output.exists()
