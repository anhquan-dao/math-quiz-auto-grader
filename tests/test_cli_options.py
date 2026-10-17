import re
from pathlib import Path

import pytest

from automarker.cli import main


@pytest.mark.parametrize('command', ['build-template', 'extract', 'download-model',
                                     'recognize', 'compare', 'run', 'report', 'review'])
def test_readme_lists_every_cli_option(command, capsys):
    with pytest.raises(SystemExit) as exc:
        main([command, '--help'])
    assert exc.value.code == 0
    options = set(re.findall(r'--[a-z][a-z-]*', capsys.readouterr().out))
    readme = Path('README.md').read_text(encoding='utf-8')
    assert options <= set(re.findall(r'--[a-z][a-z-]*', readme))


@pytest.mark.parametrize('command', ['extract', 'run'])
@pytest.mark.parametrize('tighten_args, enabled, padding, mode, static_mm', [
    ([], True, 1.5, 'both', 1.5), (['--no-tighten-ew'], False, 1.5, 'both', 1.5),
    (['--tighten-ew', '--tighten-padding-mm', '.7'], True, .7, 'both', 1.5),
    (['--tighten-mode', 'static', '--static-tighten-mm', '.8'], True, 1.5, 'static', .8),
    (['--tighten-mode', 'dynamic'], True, 1.5, 'dynamic', 1.5)])
def test_crop_options_reach_the_batch_workflow(tmp_path, monkeypatch, command,
                                              tighten_args, enabled, padding, mode, static_mm):
    from automarker import cli, template, workflow

    calls = []
    monkeypatch.setattr(cli, 'read_json', lambda path: {})
    monkeypatch.setattr(workflow, 'collect_images', lambda paths: paths)
    monkeypatch.setattr(template, 'build_template', lambda *args: {})

    def process(*args, **kwargs):
        calls.append((args, kwargs))
        return {'successful': [], 'failed': []}

    monkeypatch.setattr(workflow, 'process_captures', process)
    required = ['--template', 'template.json'] if command == 'extract' else [
        '--tex', 'quiz.tex', '--pdf', 'quiz.pdf']
    assert main(['--log', str(tmp_path/'test.log'), command, *required,
                 '--images', 'phone.jpg', '--inset-mm', '.1', '--box-mode', 'template',
                 '--box-search-mm', '3', '--south-mm', '4', '--keep-south-border', '--debug-images',
                 *tighten_args]) == 0
    args, kwargs = calls[0]
    assert args[4] == .1
    expected = {'box_mode': 'template', 'box_search_mm': 3.,
                'south_mm': 4., 'keep_south_border': True, 'debug_images': True,
                'south_border_method': 'bidirectional-recovery', 'horizontal_dilation_width_px': 15,
                'tighten_ew': enabled, 'tighten_padding_mm': padding,
                'tighten_mode': mode, 'static_tighten_mm': static_mm}
    if command == 'extract':
        expected['variant'] = 'normalized'
    assert kwargs == expected


@pytest.mark.parametrize('command', ['extract', 'run'])
@pytest.mark.parametrize('method', ['bidirectional-recovery', 'protected-crossings'])
def test_border_method_and_recovery_span_reach_workflow(tmp_path, monkeypatch, command, method):
    from automarker import cli, template, workflow

    calls = []
    monkeypatch.setattr(cli, 'read_json', lambda path: {})
    monkeypatch.setattr(template, 'build_template', lambda *args: {})
    monkeypatch.setattr(workflow, 'collect_images', lambda paths: paths)

    def process(*args, **kwargs):
        calls.append(kwargs)
        return {'successful': [], 'failed': []}

    monkeypatch.setattr(workflow, 'process_captures', process)
    required = ['--template', 'template.json'] if command == 'extract' else [
        '--tex', 'quiz.tex', '--pdf', 'quiz.pdf']
    assert main(['--log', str(tmp_path/'test.log'), command, *required, '--images', 'phone.jpg',
                 '--south-border-method', method, '--horizontal-dilation-width-px', '9']) == 0
    assert calls[0]['south_border_method'] == method
    assert calls[0]['horizontal_dilation_width_px'] == 9


@pytest.mark.parametrize('command', ['extract', 'run'])
def test_unknown_border_method_is_rejected(command):
    required = ['--template', 'template.json'] if command == 'extract' else [
        '--tex', 'quiz.tex', '--pdf', 'quiz.pdf']
    with pytest.raises(SystemExit) as exc:
        main([command, *required, '--images', 'phone.jpg', '--south-border-method', 'unknown'])
    assert exc.value.code == 2
