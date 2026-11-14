from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from worker.controller import MiningController  # noqa: E402


def test_stop_keeps_thread_ref_on_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    stuck = threading.Event()

    def _never_die(session: int) -> None:
        stuck.wait(30)

    c._run = _never_die  # type: ignore[method-assign]
    c._session_gen = 0
    c._stop.clear()
    c._session_gen = 1
    c._run_session = 1
    c._thread = threading.Thread(target=lambda: c._run(1), daemon=True)
    c._thread.start()
    time.sleep(0.05)
    # join kisa olsun
    real_join = threading.Thread.join

    def short_join(self, timeout=None):
        return real_join(self, timeout=0.2)

    monkeypatch.setattr(threading.Thread, "join", short_join)
    ok = c.stop()
    assert ok is False
    assert c._thread is not None and c._thread.is_alive()
    assert c._stop_failed is True
    stuck.set()
    c._thread.join(timeout=2)


def test_start_blocked_while_stop_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    c._stop_failed = True
    c._thread = None
    try:
        c.start("bc1qar0srrr7xfkvy5l643lydnw9re59gxgem9wg5z", test_mode=True, network_id="btc")
        assert False, "should raise"
    except RuntimeError as exc:
        assert "stop" in str(exc).lower() or "failed" in str(exc).lower()
