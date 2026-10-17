import http.client
import json
import threading

import numpy as np
import pytest

from automarker.assessment import read_assessment
from automarker.io import write_image, write_json
from automarker.report import build_archive
from automarker.review_server import ReviewServer


@pytest.fixture
def review_service(tmp_path):
    for i in range(2):
        capture = tmp_path / "captures" / str(i)
        write_image(capture / "crop.png", np.full((20, 100, 3), 255, np.uint8))
        write_json(capture / "recognition.json", {"input": f"paper_{i}.jpg", "page": 1,
                   "answers": [{"id": "answer_001", "files": {"normalized": "crop.png"},
                                "ocr": {"latex": str(i)}}]})
    root = tmp_path / "archive"
    build_archive(tmp_path / "captures", root,
                  {"answers": {"answer_001": {"mode": "exact", "value": "0"}}})
    with ReviewServer(root) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=5)


def request(server, method="GET", data=None, headers=None, path="/api/assessment"):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    defaults = {"Origin": server.origin, "X-AutoMarker-Token": server.token,
                "Content-Type": "application/json"}
    defaults.update(headers or {})
    connection.request(method, path, json.dumps(data) if data is not None else None, defaults)
    response = connection.getresponse()
    status, body = response.status, response.read()
    connection.close()
    return status, json.loads(body)


def save_payload(snapshot, source="paper_0.jpg", verdict="incorrect"):
    return {"archive_id": snapshot["archive_id"], "source_image": source, "page": "1",
            "version": snapshot["versions"][json.dumps([source, "1"], separators=(",", ":"))],
            "approved": True, "edits": [{"answer_id": "answer_001", "verdict": verdict,
                                           "notes": 'Reviewer, "quotes"\nSecond line'}]}


def test_automatic_csv_association_approved_saves_and_conflicts(review_service):
    server = review_service
    status, snapshot = request(server)
    assert status == 200
    assert [r["verdict"] for r in snapshot["rows"]] == ["correct", "incorrect"]
    before = read_assessment(server.csv_path)
    payload = save_payload(snapshot)
    status, saved = request(server, "POST", payload)
    assert status == 200
    current = read_assessment(server.csv_path)
    assert current[0]["auto_verdict"] == "correct"
    assert current[0]["verdict"] == "incorrect"
    assert current[0]["reviewed_at"].endswith("Z")
    assert current[1] == before[1]
    original = server.csv_path.read_bytes()
    assert request(server, "POST", payload)[0] == 409
    assert server.csv_path.read_bytes() == original
    # A change to a different paper does not invalidate this paper's saved revision.
    assert request(server, "POST", save_payload(snapshot, "paper_1.jpg", "correct"))[0] == 200
    assert read_assessment(server.csv_path)[0] == current[0]
    assert saved["rows"][0]["notes"] == payload["edits"][0]["notes"]


@pytest.mark.parametrize("failure,status", [("no_approval", 403), ("bad_token", 403),
                         ("bad_origin", 403), ("wrong_quiz", 400), ("wrong_paper", 400),
                         ("partial", 400), ("wrong_answer", 400)])
def test_unapproved_or_invalid_requests_never_write(review_service, failure, status):
    server = review_service
    _, snapshot = request(server)
    payload = save_payload(snapshot)
    headers = {}
    if failure == "no_approval":
        payload["approved"] = False
    elif failure == "bad_token":
        headers["X-AutoMarker-Token"] = "wrong"
    elif failure == "bad_origin":
        headers["Origin"] = "https://example.com"
    elif failure == "wrong_quiz":
        payload["archive_id"] = "another-quiz"
    elif failure == "wrong_paper":
        payload["source_image"] = "unlisted.jpg"
    elif failure == "partial":
        payload["edits"][0]["verdict"] = "partial"
    elif failure == "wrong_answer":
        payload["edits"][0]["answer_id"] = "outside-this-paper"
    before = server.csv_path.read_bytes()
    assert request(server, "POST", payload, headers)[0] == status
    assert server.csv_path.read_bytes() == before


def test_locked_csv_and_path_traversal_are_rejected(review_service, monkeypatch):
    server = review_service
    _, snapshot = request(server)
    original = server.csv_path.read_bytes()

    def locked(*args):
        raise PermissionError("Locked by another application")

    monkeypatch.setattr("automarker.review_server.write_assessment", locked)
    assert request(server, "POST", save_payload(snapshot))[0] == 423
    assert server.csv_path.read_bytes() == original
    assert request(server, path="/../assessment.py")[0] == 404
    assert request(server, headers={"Host": "example.com"})[0] == 403
