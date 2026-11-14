"""
Gecerlilik↔submit yarisi and block_store drain/writer again startma.

Test edilen:
- submit_share cnetworkrheat ordersinda _job_lock tutulur; invalidate this kritik bdeadme giremez
- drain, devam eden _flush bitene kadar bekler
- stop afreandrsei ensure_writer with queue again joblenir

Canli pool / GPU none.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.block_store import BlockCandidateStore  # noqa: E402
from mining.job import job_from_notify  # noqa: E402


def _job():
    return job_from_notify(
        ["j", "00" * 32, "00", "00", [], "20000000", "1d00ffff", "5a000000", True],
        "ab",
        4,
        1.0,
        1,
    )


def test_submit_critical_section_holds_job_lock_against_invalidate(isolated_controller):
    ctrl = isolated_controller()
    ctrl.test_mode = False
    ctrl.address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    ctrl._stratum = MagicMock()
    ctrl._stratum.session_id = 1
    ctrl._stratum.allocate_request_id.return_value = 9
    ctrl._work_epoch = 1

    saw_lock = threading.Event()
    invalidate_entered = threading.Event()
    order: list[str] = []

    def submit_share(*_a, **_k):
        order.append("submit")
        assert ctrl._job_lock.locked()
        saw_lock.set()
        # Invalidate parallel denensin — lock yuzunden submit bitene kadar beklemeli
        def inv():
            order.append("inv_wait")
            with ctrl._job_lock:
                order.append("inv_in")
                ctrl._work_epoch += 1
                invalidate_entered.set()

        t = threading.Thread(target=inv, daemon=True)
        t.start()
        time.sleep(0.15)  # invalidate'in lock beklemesini gor
        assert not invalidate_entered.is_set()
        order.append("submit_done")
        t.join(timeout=2)

    ctrl._stratum.submit_share.side_effect = submit_share

    job = _job()
    batch = job.allocate_batch(4, validity_epoch=1, session_id=1)
    assert batch is not None
    snap = replace(
        batch.snapshot,
        share_target_value=(1 << 256) - 1,
        network_target_value=(1 << 256) - 1,
    )
    work = replace(batch, snapshot=snap)
    v = snap.verify_nonce(work.start_nonce)
    assert v is not None

    ctrl._handle_verified(work, v)
    assert saw_lock.wait(2)
    assert invalidate_entered.wait(2)
    assert order.index("submit") < order.index("submit_done") < order.index("inv_in")
    assert ctrl._work_epoch == 2  # invalidate submit afreandrsei jobledi
    # Gercek store'a yazilmadi
    ctrl._explorer.watch.assert_not_called()


def test_drain_waits_for_in_progress_flush(tmp_path: Path):
    path = tmp_path / "blocks.json"
    store = BlockCandidateStore(path=path)
    original_flush = store._flush
    started = threading.Event()

    def slow_flush(batch, *, already_marked: bool = False):
        started.set()
        time.sleep(0.35)
        original_flush(batch, already_marked=already_marked)

    store._flush = slow_flush  # type: ignore[method-assign]
    store.enqueue_upsert(
        {
            "hash": "aa" * 32,
            "header80": "00" * 80,
            "job_id": "j",
            "nonce_hex": "00000001",
            "extranonce2": "00" * 4,
            "ntime": "01020304",
            "found_at": "2026-01-01 00:00:00",
        }
    )
    assert started.wait(2.0)
    t0 = time.time()
    err = store.drain(timeout_s=3.0)
    elapsed = time.time() - t0
    assert err is None
    assert elapsed >= 0.25  # yazim bitmeden donmedi
    assert path.is_file()
    store.stop()


def test_writer_restarts_after_stop(tmp_path: Path):
    path = tmp_path / "blocks2.json"
    store = BlockCandidateStore(path=path)
    store.enqueue_upsert(
        {
            "hash": "bb" * 32,
            "job_id": "j1",
            "nonce_hex": "00000002",
            "extranonce2": "00" * 4,
            "ntime": "01020304",
            "header80": "11" * 80,
            "found_at": "2026-01-01 00:00:01",
        }
    )
    store.drain(timeout_s=2.0)
    store.stop()
    assert store._thread is None or not store._thread.is_alive()

    # Durdur → Baslat esdegeri
    store.ensure_writer()
    assert store._thread is not None and store._thread.is_alive()
    store.enqueue_upsert(
        {
            "hash": "cc" * 32,
            "job_id": "j2",
            "nonce_hex": "00000003",
            "extranonce2": "00" * 4,
            "ntime": "01020304",
            "header80": "22" * 80,
            "found_at": "2026-01-01 00:00:02",
        }
    )
    err = store.drain(timeout_s=2.0)
    assert err is None
    data = path.read_text(encoding="utf-8")
    assert "cc" * 32 in data or "cccccccccccccccc" in data
    store.stop()
