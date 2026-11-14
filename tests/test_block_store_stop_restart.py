"""block-store join timeout → zombie writer again does not open."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.block_store import BlockCandidateStore  # noqa: E402


def test_stop_timeout_keeps_thread_ref_and_ensure_writer_waits(tmp_path):
    store = BlockCandidateStore(path=tmp_path / "blocks.json")
    # Gercek writer’i stop; yerine tutulmus zombie koy
    store._stop.set()
    store._wake.set()
    if store._thread is not None:
        store._thread.join(timeout=3)

    hold = threading.Event()
    old_stop = store._stop

    def zombie():
        hold.wait(30)

    t = threading.Thread(target=zombie, name="block-store-zombie", daemon=True)
    store._thread = t
    store._stop = old_stop
    store._stop.set()
    t.start()

    store.stop()
    assert store._thread is t
    assert t.is_alive()

    # ensure_writer stop set + liand thread iken ikinci writer acmamali
    store.ensure_writer()
    assert store._thread is t
    assert store._stop.is_set()

    hold.set()
    t.join(timeout=2)
    assert not t.is_alive()

    store.ensure_writer()
    assert store._thread is not None
    assert store._thread is not t
    assert store._thread.is_alive()
    assert not store._stop.is_set()
    store.stop()


def test_ensure_writer_after_clean_stop(tmp_path):
    store = BlockCandidateStore(path=tmp_path / "b2.json")
    t0 = store._thread
    store.stop()
    assert store._thread is None or not store._thread.is_alive()
    store.ensure_writer()
    assert store._thread is not None
    assert store._thread.is_alive()
    assert store._thread is not t0 or t0 is None or not t0.is_alive()
    store.stop()
