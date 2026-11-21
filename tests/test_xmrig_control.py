from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.xmrig_control import pause_xmrig, resume_xmrig, xmrig_json_rpc  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    last_method = ""
    token = "test-token"

    def do_POST(self):  # noqa: N802
        auth = self.headers.get("Authorization") or ""
        if auth != f"Bearer {self.token}":
            self.send_response(403)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        payload = json.loads(body.decode("utf-8"))
        _Handler.last_method = str(payload.get("method") or "")
        data = json.dumps({"result": {"status": "OK"}, "jsonrpc": "2.0", "id": 1})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data.encode("utf-8"))

    def log_message(self, *_args):
        return


def test_json_rpc_pause_resume_localhost():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        assert pause_xmrig(http_port=port, http_token="test-token") is True
        assert _Handler.last_method == "pause"
        assert resume_xmrig(http_port=port, http_token="test-token") is True
        assert _Handler.last_method == "resume"
        # Wrong token fails
        assert pause_xmrig(http_port=port, http_token="wrong") is False
    finally:
        server.shutdown()
