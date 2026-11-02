"""Small authenticated artifact HTTP boundary, outside the training loop."""

from __future__ import annotations

import hmac
import json
import logging
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from pbl4.common.hashing import canonical_json_bytes
from pbl4.runtime.checkpoint_artifacts import CheckpointArtifacts

logger = logging.getLogger(__name__)


class ArtifactHTTP:
    def __init__(self, host: str, port: int, token: str, artifacts: CheckpointArtifacts):
        if not token:
            raise ValueError("Artifact HTTP requires a token")
        slots = threading.BoundedSemaphore(4)

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass  # Never log credentials or payloads.

            def setup(self):
                super().setup()
                self.connection.settimeout(30)

            def _json(self, status: int, value: dict):
                raw = canonical_json_bytes(value)
                if status >= 400:
                    # Rejected POST bodies may be unread; never reuse that connection.
                    self.close_connection = True
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _handle(self):
                authorization = self.headers.get("Authorization", "")
                if not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
                    self._json(401, {"error": "Unauthorized"})
                    return
                if not slots.acquire(blocking=False):
                    self._json(503, {"error": "Artifact service busy"})
                    return
                try:
                    url = urlsplit(self.path)
                    if self.command == "GET" and url.path == "/inventory":
                        query = parse_qs(url.query)
                        self._json(
                            200,
                            artifacts.inventory(
                                query.get("after", [""])[0], int(query.get("limit", ["100"])[0])
                            ),
                        )
                        return
                    if self.command != "POST" or url.path not in ("/export", "/purge"):
                        self._json(404, {"error": "Unknown artifact operation"})
                        return
                    if "Transfer-Encoding" in self.headers:
                        raise ValueError("Chunked requests are not supported")
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1_048_576:
                        raise ValueError("Invalid artifact request length")
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise ValueError("Incomplete artifact request")
                    body = json.loads(raw)
                    if url.path == "/purge":
                        artifacts.purge(body["descriptor"])
                        self._json(200, {"deleted": True})
                        return
                    if "Range" in self.headers:
                        self._json(416, {"error": "Range is not supported"})
                        return
                    with artifacts.export(body["descriptor"], body["contract"]) as archive:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/zip")
                        self.send_header("Content-Length", str(archive.stat().st_size))
                        self.send_header("Accept-Ranges", "none")
                        self.end_headers()
                        try:
                            with archive.open("rb") as stream:
                                shutil.copyfileobj(stream, self.wfile, length=65536)
                        except OSError:
                            # Headers already promised a ZIP; abort the incomplete body.
                            self.close_connection = True
                except FileNotFoundError:
                    self._json(404, {"error": "Checkpoint artifact is missing"})
                except (ValueError, KeyError, TypeError, UnicodeError):
                    self._json(409, {"error": "Invalid checkpoint artifact or request"})
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
                except OSError:
                    logger.exception("Artifact storage operation failed")
                    self._json(503, {"error": "Artifact storage unavailable"})
                finally:
                    slots.release()

            do_GET = _handle
            do_POST = _handle

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="pbl4-artifacts", daemon=True
        )

    @property
    def address(self):
        return self._server.server_address

    def start(self):
        self._thread.start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
