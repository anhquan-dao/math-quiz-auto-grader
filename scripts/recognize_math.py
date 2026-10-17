"""Thin wrapper for python scripts/recognize_math.py --extraction ... --model ..."""
import sys

from automarker.cli import main

raise SystemExit(main(["recognize", *sys.argv[1:]]))
