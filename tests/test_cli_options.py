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
def test_crop_options_reach_the_batch_workflow(tmp_path, monkeypatch, command):
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
                 '--box-search-mm', '3', '--south-mm', '4', '--keep-south-border']) == 0
    args, kwargs = calls[0]
    assert args[4] == .1
    assert kwargs == {'box_mode': 'template', 'box_search_mm': 3.,
                      'south_mm': 4., 'keep_south_border': True}
