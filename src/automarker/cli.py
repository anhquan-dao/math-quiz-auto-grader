"""Command line entry point; every command emits a DEBUG-level file log."""

import argparse
import logging
from pathlib import Path

from .io import configure_logging, read_json, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline quiz alignment and math OCR")
    parser.add_argument("--verbose", action="store_true", help="Also show DEBUG logs in console")
    parser.add_argument("--log", type=Path, default=Path("outputs/logs/automarker.log"))
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-template", help="Match TeX boxes to vector PDF geometry")
    build.add_argument("--tex", type=Path, required=True)
    build.add_argument("--pdf", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--dpi", type=int, default=200)
    build.add_argument("--dictionary", default="auto")
    build.add_argument("--marker-map", type=Path, help="Explicit canonical marker map in PDF points")
    build.add_argument("--calibration-image", type=Path,
                       help="One clear tagged photo when the PDF itself has no tags")
    extract = sub.add_parser("extract", help="Align photos and save answer crops")
    extract.add_argument("--template", type=Path, required=True)
    extract.add_argument("--images", type=Path, nargs="+", required=True,
                         help="Image files or directories (nonrecursive)")
    extract.add_argument("--output", type=Path, default=Path("outputs/captures"))
    extract.add_argument("--page", type=int, default=1)
    extract.add_argument("--inset-mm", type=float, default=1.5)
    download = sub.add_parser("download-model", help="Provision model weights (requires internet)")
    download.add_argument("--output", type=Path, default=Path("models/pix2text-mfr"))
    download.add_argument("--revision", default="main")
    ocr = sub.add_parser("recognize", help="Recognize extracted math using local weights only")
    ocr.add_argument("--extraction", type=Path, required=True)
    ocr.add_argument("--model", type=Path, default=Path("models/pix2text-mfr"))
    ocr.add_argument("--variant", choices=("raw", "normalized", "binary"), default="normalized")
    ocr.add_argument("--max-tokens", type=int, default=256)
    grade = sub.add_parser("compare", help="Compare OCR to a supplied answer key for review")
    grade.add_argument("--recognition", type=Path, required=True)
    grade.add_argument("--key", type=Path, required=True)
    grade.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run", help="Build a template, extract all captures, and run offline OCR")
    run.add_argument("--tex", type=Path, required=True)
    run.add_argument("--pdf", type=Path, required=True)
    run.add_argument("--images", type=Path, nargs="+", required=True)
    run.add_argument("--output", type=Path, default=Path("outputs/run"))
    run.add_argument("--model", type=Path, default=Path("models/pix2text-mfr"))
    expected = run.add_mutually_exclusive_group()
    expected.add_argument("--key", type=Path, help="Optional answer key for candidate comparison")
    expected.add_argument("--demo-expected", action="store_true",
                          help="Use visibly labeled made-up expected answers in the HTML archive")
    run.add_argument("--dpi", type=int, default=200)
    run.add_argument("--dictionary", default="auto")
    run.add_argument("--marker-map", type=Path)
    run.add_argument("--calibration-image", type=Path)
    run.add_argument("--page", type=int, default=1)
    run.add_argument("--inset-mm", type=float, default=1.5)
    run.add_argument("--variant", choices=("raw", "normalized", "binary"), default="normalized")
    run.add_argument("--max-tokens", type=int, default=256)
    run.add_argument("--review", action="store_true", help="Open the local quiz reviewer after processing")
    run.add_argument("--port", type=int, default=8765, help="Local review port when --review is used")
    report = sub.add_parser("report", help="Create a portable offline HTML review archive")
    report.add_argument("--captures", type=Path, required=True,
                        help="One capture directory or a directory containing captures")
    report.add_argument("--output", type=Path, default=Path("outputs/archive"))
    report_expected = report.add_mutually_exclusive_group()
    report_expected.add_argument("--key", type=Path, help="Answer key containing expected values")
    report_expected.add_argument("--demo-expected", action="store_true",
                                 help="Display made-up expectations, labeled as demo values")
    review = sub.add_parser("review", help="Review one quiz with its automatically associated CSV")
    review.add_argument("--archive", type=Path, required=True)
    review.add_argument("--port", type=int, default=8765)
    review.add_argument("--open", action="store_true", help="Open the reviewer in the default browser")
    args = parser.parse_args(argv)
    configure_logging(args.log, args.verbose)
    log = logging.getLogger(__name__)
    try:
        if args.command == "build-template":
            from .template import build_template
            build_template(args.tex, args.pdf, args.output, args.dpi, args.dictionary,
                           read_json(args.marker_map) if args.marker_map else None,
                           args.calibration_image)
        elif args.command == "extract":
            from .workflow import collect_images, process_captures
            template = read_json(args.template)
            summary = process_captures(collect_images(args.images), template, args.output,
                                       args.page, args.inset_mm)
            return 1 if summary["failed"] else 0
        elif args.command == "run":
            from .report import build_archive
            from .template import build_template
            from .workflow import collect_images, process_captures
            if args.max_tokens < 1:
                raise ValueError("max_tokens must be positive")
            paths = collect_images(args.images)
            key = read_json(args.key) if args.key else None
            template = build_template(args.tex, args.pdf, args.output / "template/template.json",
                                       args.dpi, args.dictionary,
                                       read_json(args.marker_map) if args.marker_map else None,
                                       args.calibration_image)
            summary = process_captures(paths, template, args.output / "captures", args.page,
                                       args.inset_mm, args.model, args.variant, args.max_tokens, key)
            if summary["successful"]:
                build_archive(args.output / "captures", args.output / "archive", key,
                              args.demo_expected, quiz_name=args.tex.stem)
                if args.review:
                    from .review_server import serve_review
                    serve_review(args.output / "archive", args.port, open_browser=True)
            return 1 if summary["failed"] else 0
        elif args.command == "report":
            from .report import build_archive
            build_archive(args.captures, args.output, read_json(args.key) if args.key else None,
                          args.demo_expected)
        elif args.command == "review":
            from .review_server import serve_review
            serve_review(args.archive, args.port, args.open)
        elif args.command == "download-model":
            from .ocr import download_model
            download_model(args.output, args.revision)
        elif args.command == "recognize":
            from .ocr import recognize_extraction
            recognize_extraction(args.extraction, args.model, args.variant, args.max_tokens)
        elif args.command == "compare":
            from .grading import compare_answers
            write_json(args.output, compare_answers(read_json(args.recognition), read_json(args.key)))
    except Exception:
        log.exception("Command failed")
        return 1
    return 0
