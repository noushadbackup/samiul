"""Local HTTP server imitating the YouTube Data API v3 — FOR TESTING ONLY.

Serves the in-memory FakeYouTube MOCK data so the real CLI (run.py) can be
exercised end-to-end without network access or an API key. Output produced
against this server is MOCK output and must never be used as research data.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from tests.conftest import FakeYouTube


def start_server(fake: FakeYouTube | None = None) -> tuple[ThreadingHTTPServer, str]:
    fake = fake or FakeYouTube(n_videos=30, n_channels=10, comments_per_video=80)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            resp = fake.request("GET", f"http://mock{parsed.path}", params=params)
            body = json.dumps(resp.json(), ensure_ascii=False).encode("utf-8")
            self.send_response(resp.status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/youtube/v3"
