"""Thin wrapper for python scripts/build_template.py --tex ... --pdf ... --output ..."""
import sys

from automarker.cli import main

raise SystemExit(main(["build-template", *sys.argv[1:]]))
