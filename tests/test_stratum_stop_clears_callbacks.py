"""Stratum stop → callback kesilir (zombie job basmaz)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from stratum.client import StratumClient  # noqa: E402


def test_stop_nulls_callbacks():
    jobs = []
    c = StratumClient(
        host="127.0.0.1",
        port=3333,
        on_job=lambda p, clean: jobs.append((p, clean)),
        on_difficulty=lambda d: None,
        on_status=lambda s: None,
        on_submit_result=lambda *a: None,
    )
    assert c.on_job is not None
    c.stop()
    assert c.on_job is None
    assert c.on_difficulty is None
    assert c.on_status is None
    assert c.on_submit_result is None
    # Notify yolu callback yoksa no-op
    c._handle_notify_method(
        "mining.notify", ["job", "0" * 64, "", "", [], "0", "0", "0", True]
    )
    assert jobs == []


def test_stop_notifies_inflight_submit_before_clearing_submit_cb():
    seen: list[dict] = []

    def on_submit(ok, msg, meta):
        seen.append({"ok": ok, "msg": msg, "meta": meta})

    c = StratumClient(
        host="127.0.0.1",
        port=3333,
        on_submit_result=on_submit,
    )
    event = __import__("threading").Event()
    holder = {"callback": lambda *a: None}
    with c._lock:
        c._pending[42] = {"event": event, "holder": holder, "is_submit": True}
        c.session_id = 7
    c.stop()
    assert c.on_submit_result is None
    assert len(seen) == 1
    assert seen[0]["meta"].get("outcome_unknown") is True
    assert 42 not in c._pending


def test_connect_aborts_when_stop_set(monkeypatch):
    c = StratumClient(host="127.0.0.1", port=3333)
    c._stop.set()
    sock = MagicMock()
    monkeypatch.setattr(
        "stratum.client.socket.create_connection", lambda *a, **k: sock
    )
    try:
        c._connect_and_handshake()
        assert False, "should raise"
    except ConnectionError as exc:
        assert "stop" in str(exc).lower() or "iptal" in str(exc).lower()
    sock.close.assert_called()
