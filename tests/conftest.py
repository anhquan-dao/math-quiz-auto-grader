"""Keep test scratch files inside the project, including on a fresh checkout."""

from pathlib import Path


def pytest_configure(config):
    if config.option.basetemp:
        Path(config.option.basetemp).parent.mkdir(parents=True, exist_ok=True)
