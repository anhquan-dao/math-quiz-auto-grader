"""Loopback-only review service bound to one quiz archive and its assessment.csv."""

import json
import logging
import mimetypes
import secrets
import threading
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .assessment import page_version, read_assessment, write_assessment
from .io import read_json

LOG = logging.getLogger(__name__)


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, archive: Path, port: int = 0):
        self.archive = archive.resolve()
        manifest = read_json(self.archive / "archive.json")
        self.archive_id = manifest["archive_id"]
        self.csv_path = self.archive / "assessment.csv"
        if not self.csv_path.resolve().is_relative_to(self.archive):
            raise ValueError("Assessment CSV must stay inside this quiz archive")
        self.pages = {(p["source"], str(p.get("page", 1))) for p in manifest["pages"]}
        self.answer_counts = {(p["source"], str(p.get("page", 1))): p["answers"] for p in manifest["pages"]}
        self.token = secrets.token_urlsafe(32)
        self.write_lock = threading.Lock()
        read_assessment(self.csv_path)
        super().__init__(("127.0.0.1", port), ReviewHandler)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"

    def current_rows(self) -> list[dict]:
        return [r for r in read_assessment(self.csv_path) if r["archive_id"] == self.archive_id]

    def snapshot(self) -> dict:
        rows = self.current_rows()
        versions = {json.dumps([source, page], separators=(",", ":"), ensure_ascii=False):
                    page_version([r for r in rows if r["source_image"] == source and r["page"] == page])
                    for source, page in self.pages}
        return {"archive_id": self.archive_id, "rows": rows, "versions": versions, "token": self.token}


class ReviewHandler(BaseHTTPRequestHandler):
    server: ReviewServer

    def log_message(self, format: str, *args) -> None:
        LOG.debug("%s %s", self.client_address[0], format % args)

    def respond(self, status: int, data: bytes, mime: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def json_response(self, status: int, data: dict) -> None:
        self.respond(status, json.dumps(data, ensure_ascii=False).encode())

    def trusted_host(self) -> bool:
        return self.headers.get("Host") == self.server.origin.removeprefix("http://")

    def do_GET(self) -> None:
        if not self.trusted_host():
            self.json_response(403, {"error": "Invalid review host"})
            return
        route = urlsplit(self.path).path
        try:
            if route == "/api/assessment":
                with self.server.write_lock:
                    self.json_response(200, self.server.snapshot())
                return
            target = (self.server.archive / unquote(route).lstrip("/")).resolve()
            if route == "/":
                target = self.server.archive / "index.html"
            if not target.is_relative_to(self.server.archive) or not target.is_file():
                self.json_response(404, {"error": "File not found"})
                return
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.respond(200, target.read_bytes(), mime + "; charset=utf-8")
        except Exception:
            LOG.exception("Could not load review data")
            self.json_response(500, {"error": "Could not read this quiz's assessment file"})

    def do_POST(self) -> None:
        if (not self.trusted_host() or self.headers.get("Origin") != self.server.origin or
                not secrets.compare_digest(self.headers.get("X-AutoMarker-Token", "").encode(), self.server.token.encode())):
            self.json_response(403, {"error": "Review permission token or origin is invalid"})
            return
        if urlsplit(self.path).path != "/api/assessment":
            self.json_response(404, {"error": "Unknown review operation"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                raise ValueError("Invalid save request size")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise TypeError("Invalid save request")
            if data.get("approved") is not True:
                self.json_response(403, {"error": "Explicit approval is required for each page save"})
                return
            source, page = data.get("source_image"), str(data.get("page"))
            if data.get("archive_id") != self.server.archive_id or (source, page) not in self.server.pages:
                raise ValueError("The save request does not belong to this quiz")
            edits = data.get("edits")
            if not isinstance(edits, list) or any(not isinstance(e, dict) for e in edits):
                raise ValueError("Invalid verdict edits")
            if any(e.get("verdict") not in {"correct", "incorrect"} or
                   not isinstance(e.get("notes", ""), str) for e in edits):
                raise ValueError("Choose correct or incorrect for every answer before saving")
            with self.server.write_lock:
                rows = read_assessment(self.server.csv_path)
                selected = [r for r in rows if r["archive_id"] == self.server.archive_id and
                            r["source_image"] == source and r["page"] == page]
                by_id = {e.get("answer_id"): e for e in edits}
                if (len(selected) != self.server.answer_counts[source, page] or
                        len(by_id) != len(edits) or set(by_id) != {r["answer_id"] for r in selected}):
                    raise ValueError("The save must contain exactly this paper's answers")
                if data.get("version") != page_version(selected):
                    self.json_response(409, {"error": "This paper changed elsewhere. Reload saved verdicts before saving again."})
                    return
                stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                for row in selected:
                    row.update(verdict=by_id[row["answer_id"]]["verdict"],
                               notes=by_id[row["answer_id"]].get("notes", ""), reviewed_at=stamp)
                write_assessment(self.server.csv_path, rows)
                LOG.info("Approved page save: %s page %s, %d verdicts", source, page, len(selected))
                self.json_response(200, self.server.snapshot())
        except (ValueError, TypeError, KeyError) as exc:
            self.json_response(400, {"error": str(exc)})
        except PermissionError:
            LOG.exception("Assessment CSV is locked or not writable")
            self.json_response(423, {"error": "The assessment CSV is locked or not writable. Close it in other applications and retry."})
        except Exception:
            LOG.exception("Could not save reviewed verdicts")
            self.json_response(500, {"error": "Could not save this paper; the CSV was not replaced"})


def serve_review(archive: Path, port: int = 8765, open_browser: bool = False) -> None:
    with ReviewServer(archive, port) as server:
        url = server.origin + "/index.html"
        LOG.info("Review this quiz at %s; CSV: %s; stop with Ctrl+C", url, server.csv_path)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            LOG.info("Review server stopped")
