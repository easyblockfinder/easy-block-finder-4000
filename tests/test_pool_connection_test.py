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

from networks.pool_connection_test import probe_native_pool_connection  # noqa: E402


class _FakeStratum:
    """Minimal stratum V1 server for unit tests."""

    def __init__(self, *, send_notify: bool = True, accept_auth: bool = True) -> None:
        self.send_notify = send_notify
        self.accept_auth = accept_auth
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2)

    def _serve(self) -> None:
        self._sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle(conn)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(5)
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                msg = json.loads(line.decode("utf-8"))
                mid = msg.get("id")
                method = msg.get("method")
                if method == "mining.subscribe":
                    conn.sendall(
                        (
                            json.dumps(
                                {
                                    "id": mid,
                                    "result": [[["mining.notify", "ae"]], "ex1", 4],
                                    "error": None,
                                }
                            )
                            + "\n"
                        ).encode()
                    )
                    if self.send_notify:
                        # Some pools notify before authorize completes.
                        notify = {
                            "id": None,
                            "method": "mining.notify",
                            "params": [
                                "job1",
                                "0" * 64,
                                "00",
                                "00",
                                [],
                                "20000000",
                                "1a2b3c4d",
                                "12345678",
                                True,
                            ],
                        }
                        conn.sendall((json.dumps(notify) + "\n").encode())
                elif method == "mining.authorize":
                    conn.sendall(
                        (
                            json.dumps(
                                {
                                    "id": mid,
                                    "result": True if self.accept_auth else False,
                                    "error": None if self.accept_auth else [24, "auth", None],
                                }
                            )
                            + "\n"
                        ).encode()
                    )
                    if self.accept_auth and self.send_notify:
                        # Ensure notify even if subscribe path skipped it.
                        time.sleep(0.05)
                        notify = {
                            "id": None,
                            "method": "mining.notify",
                            "params": [
                                "job2",
                                "0" * 64,
                                "00",
                                "00",
                                [],
                                "20000000",
                                "1a2b3c4d",
                                "12345678",
                                False,
                            ],
                        }
                        conn.sendall((json.dumps(notify) + "\n").encode())
                elif method == "mining.suggest_difficulty":
                    conn.sendall(
                        (json.dumps({"id": mid, "result": True, "error": None}) + "\n").encode()
                    )
                    conn.sendall(
                        (
                            json.dumps(
                                {
                                    "id": None,
                                    "method": "mining.set_difficulty",
                                    "params": [1024],
                                }
                            )
                            + "\n"
                        ).encode()
                    )
                else:
                    conn.sendall(
                        (json.dumps({"id": mid, "result": True, "error": None}) + "\n").encode()
                    )


def test_job_required_success():
    srv = _FakeStratum(send_notify=True, accept_auth=True)
    srv.start()
    try:
        result = probe_native_pool_connection(
            host="127.0.0.1",
            port=srv.port,
            username="bc1qtestaddressfortest0000000000000",
            password="x",
            timeout_s=8.0,
        )
        assert result.ok is True
        assert result.stage == "job"
        assert result.job_id
    finally:
        srv.stop()


def test_auth_without_job_is_failure():
    srv = _FakeStratum(send_notify=False, accept_auth=True)
    srv.start()
    try:
        result = probe_native_pool_connection(
            host="127.0.0.1",
            port=srv.port,
            username="bc1qtestaddressfortest0000000000000",
            password="x",
            timeout_s=3.0,
        )
        assert result.ok is False
        assert result.stage in ("authorized", "connected", "failed")
        assert "mining.notify" in result.message.lower() or "job" in result.message.lower()
    finally:
        srv.stop()


def test_empty_user_fails():
    result = probe_native_pool_connection(
        host="127.0.0.1",
        port=1,
        username="  ",
        timeout_s=1.0,
    )
    assert result.ok is False
    assert result.stage == "failed"
