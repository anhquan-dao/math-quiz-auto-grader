"""Build an HTML archive from existing extraction/recognition results."""
import sys

from automarker.cli import main

raise SystemExit(main(["report", *sys.argv[1:]]))
