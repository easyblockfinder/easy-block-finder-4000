from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.block_store import ExplorerTracker  # noqa: E402


def test_start_after_stop_timeout_restarts_when_thread_dead():
    tr = ExplorerTracker(interval_s=60.0)
    hold = threading.Event()

    def zombie():
        hold.wait()

    t = threading.Thread(target=zombie, daemon=True)
    tr._thread = t
    tr._stop.set()
    t.start()
    # join timeout — process hâlâ liand, referans korunmali
    tr.stop()
    assert tr._thread is t
    assert t.is_alive()

    hold.set()
    t.join(timeout=2)
    assert not t.is_alive()

    tr.watch(
        {
            "hash": "aa" * 32,
            "network_id": "btc",
            "chain_status": "aday_bulundu",
        }
    )
    assert tr._thread is not None
    assert tr._thread.is_alive()
    assert tr._thread is not t
    assert not tr._stop.is_set()
    tr.stop()


def test_explorer_is_running():
    tr = ExplorerTracker(interval_s=60.0)
    assert tr.is_running() is False
    tr.watch({"hash": "bb" * 32, "network_id": "btc"})
    assert tr.is_running() is True
    tr.stop()
