import os
import shutil
import subprocess
import threading
from pathlib import Path

import numpy as np
import pytest

from automarker.assessment import read_assessment
from automarker.io import write_image, write_json
from automarker.report import build_archive
from automarker.review_server import ReviewServer


@pytest.mark.skipif(os.environ.get("AUTOMARKER_BROWSER_TESTS") != "1",
                    reason="Set AUTOMARKER_BROWSER_TESTS=1 for optional Node/Playwright checks")
def test_csv_review_permission_and_persistence_in_chrome(tmp_path):
    node = os.environ.get("AUTOMARKER_NODE") or shutil.which("node")
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
    if node is None and (bundled / "bin/node.exe").exists():
        node = str(bundled / "bin/node.exe")
    if node is None:
        pytest.fail("Browser checks require Node.js; set AUTOMARKER_NODE to its executable")
    environment = dict(os.environ)
    playwright = bundled / "node_modules/playwright"
    if "AUTOMARKER_PLAYWRIGHT" not in environment and playwright.exists():
        environment["AUTOMARKER_PLAYWRIGHT"] = str(playwright)
    captures = tmp_path / "captures"
    for i in range(2):
        capture = captures / str(i)
        write_image(capture / "crop.png", np.full((35, 120, 3), 255, np.uint8))
        write_json(capture / "recognition.json", {"input": f"phone_{i}.jpg", "page": 1,
                   "answers": [{"id": "answer_001", "files": {"normalized": "crop.png"},
                                "ocr": {"latex": "x+1"}}]})
    archive = tmp_path / "archive"
    build_archive(captures, archive, demo_expected=True)
    script = Path(__file__).with_name("browser_review.cjs").resolve()
    with ReviewServer(archive) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run([node, str(script), str(archive), str(tmp_path), server.origin],
                                    check=False, env=environment, capture_output=True, text=True, timeout=120)
        finally:
            server.shutdown()
            thread.join(timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    approved = read_assessment(tmp_path / "approved.csv")
    assert [row["auto_verdict"] for row in approved] == ["incorrect", "incorrect"]
    assert [row["verdict"] for row in approved] == ["correct", "incorrect"]
    assert approved[0]["notes"] == 'Reviewer, "quotes"\nSecond line: đúng'
    assert all(row["reviewed_at"].endswith("Z") for row in approved)
    assert all(row["reviewed_at"] for row in read_assessment(archive / "assessment.csv"))
