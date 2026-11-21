"""
Yalniz iki senaryo:
1) submit_share: expected_session_id + socket submiti connection lock altinda
2) drain: timeoutnda ikinci flush none, timeout errorsi
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.block_store import BlockCandidateStore  # noqa: E402
from stratum.client import StratumClient  # noqa: E402


def test_submit_share_session_and_socket_under_connection_lock():
    client = StratumClient()
    client.session_id = 5
    client.connected = True

    sent: list[bytes] = []
    lock_held_at_send = threading.Event()

    class FakeSock:
        def sendall(self, data: bytes) -> None:
            assert client._lock.locked(), "send connection lock disinda"
            lock_held_at_send.set()
            sent.append(data)

    client._sock = FakeSock()  # type: ignore[assignment]

    mid = client.submit_share(
        "worker",
        "job1",
        "00000000",
        "aabbccdd",
        "11223344",
        request_id=42,
        expected_session_id=5,
    )
    assert mid == 42
    assert lock_held_at_send.is_set()
    assert len(sent) == 1
    body = json.loads(sent[0].decode().strip())
    assert body["id"] == 42
    assert body["method"] == "mining.submit"

    # Oturum degjobmjobse gonderme
    client.session_id = 6
    try:
        client.submit_share(
            "worker",
            "job1",
            "00000000",
            "aabbccdd",
            "11223344",
            request_id=43,
            expected_session_id=5,
        )
        assert False, "session uyusmazligi was expected"
    except RuntimeError as exc:
        # Stable English token from StratumClient; must refuse send.
        assert "session mismatch" in str(exc).lower()
    assert len(sent) == 1  # ek submit none


def test_submit_share_aborts_if_socket_closed_under_same_lock():
    client = StratumClient()
    client.session_id = 1
    client.connected = True
    client._sock = None
    try:
        client.submit_share(
            "w",
            "j",
            "00",
            "00",
            "00",
            expected_session_id=1,
        )
        assert False, "socket none errorsi was expected"
    except RuntimeError as exc:
        assert "socket" in str(exc).lower() or "connection" in str(exc).lower()


def test_drain_timeout_no_second_flush_while_writing(tmp_path: Path):
    path = tmp_path / "blocks.json"
    store = BlockCandidateStore(path=path)
    original = store._flush
    flush_count = {"n": 0}
    started = threading.Event()

    def slow_flush(batch, *, already_marked: bool = False):
        flush_count["n"] += 1
        started.set()
        time.sleep(0.8)
        original(batch, already_marked=already_marked)

    store._flush = slow_flush  # type: ignore[method-assign]
    store.enqueue_upsert(
        {
            "hash": "ee" * 32,
            "job_id": "j",
            "nonce_hex": "00000001",
            "extranonce2": "00" * 4,
            "ntime": "01020304",
            "header80": "00" * 80,
            "found_at": "2026-01-01 00:00:00",
        }
    )
    assert started.wait(2.0)
    err = store.drain(timeout_s=0.25)
    assert err is not None
    assert "timeout" in err.lower() or "timeout" in err.lower()
    # Zaman asiminda ikinci flush none — yalnizca writer'in a flush'i
    time.sleep(1.0)
    assert flush_count["n"] == 1
    store.stop()
