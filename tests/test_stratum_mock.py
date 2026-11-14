"""Yerel dusuk zorluklu Stratum mock — real BTC uretmez."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from stratum.client import StratumClient  # noqa: E402


class _MockStratumServer:
    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(1)
        self.submit_ok = False
        self._stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop = True
        try:
            socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
        except OSError:
            pass
        self.sock.close()

    def _serve(self) -> None:
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        conn.settimeout(2.0)
        buf = b""
        try:
            while not self._stop:
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    msg = json.loads(line.decode())
                    mid = msg["id"]
                    method = msg["method"]
                    if method == "mining.subscribe":
                        resp = {
                            "id": mid,
                            "result": [[["mining.notify", "ae"]], "00112233", 4],
                            "error": None,
                        }
                    elif method == "mining.authorize":
                        resp = {"id": mid, "result": True, "error": None}
                        # authorize afreandrsei difficulty + notify
                        conn.sendall(
                            (
                                json.dumps(
                                    {
                                        "id": None,
                                        "method": "mining.set_difficulty",
                                        "params": [0.01],
                                    }
                                )
                                + "\n"
                            ).encode()
                        )
                        conn.sendall(
                            (
                                json.dumps(
                                    {
                                        "id": None,
                                        "method": "mining.notify",
                                        "params": [
                                            "job1",
                                            "0" * 64,
                                            "01000000",
                                            "00000000",
                                            [],
                                            "20000000",
                                            "1d00ffff",
                                            f"{int(time.time()):08x}",
                                            True,
                                        ],
                                    }
                                )
                                + "\n"
                            ).encode()
                        )
                    elif method == "mining.submit":
                        self.submit_ok = True
                        resp = {"id": mid, "result": True, "error": None}
                    else:
                        resp = {"id": mid, "result": None, "error": "unknown"}
                    conn.sendall((json.dumps(resp) + "\n").encode())
        finally:
            conn.close()


def test_stratum_subscribe_authorize_submit_flow():
    """TEST: mock pool — real BTC none."""
    server = _MockStratumServer()
    server.start()
    jobs = []
    diffs = []
    submits = []

    client = StratumClient(
        host="127.0.0.1",
        port=server.port,
        on_job=lambda p, c: jobs.append((p, c)),
        on_difficulty=lambda d: diffs.append(d),
        on_submit_result=lambda ok, msg, meta: submits.append(ok),
    )
    client.start("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")

    deadline = time.time() + 8
    while time.time() < deadline and (not client.authorized or not jobs):
        time.sleep(0.1)

    assert client.subscribed
    assert client.authorized
    assert client.extranonce1 == "00112233"
    assert diffs and diffs[0] == 0.01
    assert jobs and jobs[0][0][0] == "job1"

    client.submit_share(
        "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "job1",
        "00000000",
        f"{int(time.time()):08x}",
        "12345678",
        expected_session_id=client.session_id,
    )
    deadline = time.time() + 5
    while time.time() < deadline and not submits:
        time.sleep(0.05)

    client.stop()
    server.stop()
    assert submits == [True]
    assert server.submit_ok
