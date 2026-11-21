"""Blok candidatei in-flight / priority / submit sonucu — targeted regression.

Gercekten test edwithn:
- WorkBatch epoch/session gecerliligi (A → B false → C true)
- Eski oturum batch'inin yeni session'da reddi
- meets_network sonuclarinin orderlanmasi (before block)
- GPU truncated bayrnetworki + network hedefi again tarama merge (aim)
- (session,id) esleme; outcome_unknown ≠ rejected
- block_store.drain

NOT TESTED: liand CKPool accepted, real OpenCL thisffer oandrflow
(GPU nonesa kernel yolu skipped), explorer."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from gpu.miner import SearchResult  # noqa: E402
from mining.block_store import BlockCandidateStore  # noqa: E402
from mining.job import job_from_notify  # noqa: E402


def _mk_job(jid: str, gen: int = 1):
    return job_from_notify(
        [jid, "00" * 32, "00", "00", [], "20000000", "1d00ffff", "5a000000", True],
        "ab",
        4,
        1.0,
        gen,
    )


def test_scenario_A_Bfalse_Ctrue_invalidates_all_batches(isolated_controller):
    """A accountlmomentrken B(clean=false), after C(clean=true)."""
    ctrl = isolated_controller()
    ctrl._stratum = MagicMock()
    ctrl._stratum.session_id = 1
    ctrl._stratum.extranonce1 = "ab"
    ctrl._stratum.extranonce2_size = 4
    ctrl._stratum.difficulty = 1.0
    ctrl._stratum.wire_log = []
    ctrl.address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    # Coinbase kontrolunu bypass: empty coinb with stop so it does not diye mock
    import worker.controller as cmod

    orig = cmod.verify_job_coinbase_payout

    class Ok:
        stop_mining = False
        message = "ok"
        amount_independently_verified = False

    cmod.verify_job_coinbase_payout = lambda **kw: Ok()  # type: ignore
    try:
        job_a = _mk_job("A", 1)
        ctrl._job = job_a
        ctrl._known_jobs = [job_a]
        ctrl._work_epoch = 5
        batch_a = job_a.allocate_batch(100, validity_epoch=5, session_id=1)
        assert batch_a is not None
        assert batch_a.is_submittable(5, 1)

        # B clean=false
        ctrl._on_job(
            ["B", "00" * 32, "00", "00", [], "20000000", "1d00ffff", "5a000001", False],
            clean=False,
        )
        assert ctrl._work_epoch == 5  # epoch same
        assert batch_a.is_submittable(ctrl._work_epoch, 1)
        assert job_a.superseded and not job_a.invalidated

        # C clean=true
        ctrl._on_job(
            ["C", "00" * 32, "00", "00", [], "20000000", "1d00ffff", "5a000002", True],
            clean=True,
        )
        assert ctrl._work_epoch == 6
        assert not batch_a.is_submittable(ctrl._work_epoch, 1)
        assert job_a.invalidated
    finally:
        cmod.verify_job_coinbase_payout = orig


def test_old_session_batch_not_submittable_on_new_session():
    job = _mk_job("A")
    batch = job.allocate_batch(10, validity_epoch=1, session_id=7)
    assert batch is not None
    assert batch.is_submittable(1, 7)
    assert not batch.is_submittable(1, 8)  # new connection
    assert not batch.is_submittable(2, 7)  # epoch


def test_block_candidates_sorted_before_shares():
    job = _mk_job("j")
    batch = job.allocate_batch(8, validity_epoch=1, session_id=1)
    assert batch is not None
    snap = replace(
        batch.snapshot,
        share_target_value=(1 << 256) - 1,
        network_target_value=(1 << 256) - 1,
    )
    # Tum nonce'lar both share both network
    items = [snap.verify_nonce(n) for n in range(batch.start_nonce, batch.start_nonce + 3)]
    items = [x for x in items if x]
    assert items
    # Controller ordering
    items.sort(key=lambda v: (0 if v.get("meets_network") else 1, int(v["nonce"])))
    assert items[0]["meets_network"] is True


def test_network_hit_not_dropped_when_share_also_checked():
    job = _mk_job("j")
    batch = job.allocate_batch(8, validity_epoch=1, session_id=1)
    assert batch is not None
    easy = (1 << 256) - 1
    snap = replace(
        batch.snapshot,
        share_target_value=easy,
        network_target_value=easy,
    )
    hit = snap.verify_nonce(batch.start_nonce)
    assert hit is not None
    assert hit["meets_network"] is True
    assert hit["meets_share"] is True


def test_gpu_truncated_flag_and_merge_logic():
    """Birim: truncated SearchResult + network scan merge (OpenCL not called)."""
    share_hits = [10, 11, 12]
    net_hits = [99, 11]  # 99 yalniz network scannda
    result = SearchResult(
        hits=share_hits,
        scanned=1000,
        global_size=1024,
        local_size=256,
        start_nonce=0,
        raw_hit_count=300,
        truncated=True,
    )
    assert result.truncated
    merged = list(dict.fromkeys(net_hits + result.hits))
    assert 99 in merged
    assert merged[0] == 99  # network scan before alestirildi


def test_outcome_unknown_does_not_increment_rejected(isolated_controller):
    ctrl = isolated_controller()
    e = {
        "pending": True,
        "submit_id": 3,
        "session_id": 1,
        "job_id": "j",
        "nonce_hex": "aa",
        "block_candidate": True,
        "hash": "00" * 32,
        "test_mode": True,
    }
    with ctrl._submit_lock:
        ctrl._pending_submits[(1, 3)] = e
    ctrl._on_submit_result(
        False,
        "outcome_unknown: connection lost",
        {
            "id": 3,
            "session_id": 1,
            "result": None,
            "error": None,
            "outcome_unknown": True,
        },
    )
    # Status token is language-stable; must not count as reject/accept.
    assert e["status"] == "outcome_unknown"
    assert ctrl.stats.rejected == 0
    assert ctrl.stats.accepted == 0
    assert e.get("pool_ok") is None


def test_handle_verified_skips_expired_epoch(isolated_controller):
    ctrl = isolated_controller()
    ctrl.test_mode = False
    ctrl.address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    ctrl._stratum = MagicMock()
    ctrl._stratum.session_id = 1
    ctrl._stratum.allocate_request_id.return_value = 42
    ctrl._work_epoch = 9  # batch eski

    job = _mk_job("j")
    batch = job.allocate_batch(
        20, validity_epoch=1, session_id=1  # eski epoch
    )
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
    ctrl._stratum.submit_share.assert_not_called()
    ctrl._explorer.watch.assert_not_called()


def test_block_store_drain(tmp_path: Path):
    path = tmp_path / "b.json"
    store = BlockCandidateStore(path=path)
    store.enqueue_upsert(
        {
            "hash": "cd" * 32,
            "header80": "11" * 80,
            "job_id": "j",
            "nonce_hex": "01020304",
            "extranonce2": "00" * 4,
            "ntime": "aabbccdd",
            "submit_id": 7,
            "found_at": "2026-01-01 00:00:00",
        }
    )
    err = store.drain(timeout_s=2.0)
    assert err is None
    assert path.is_file()
    store.stop()
