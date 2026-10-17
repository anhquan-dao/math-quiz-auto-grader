"""Thin wrapper for python scripts/extract_answers.py --template ... --images ..."""
import sys

from automarker.cli import main

raise SystemExit(main(["extract", *sys.argv[1:]]))
