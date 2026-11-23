"""Production search-strategy wiring (no live pool required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.job import MiningJob, job_from_notify  # noqa: E402
from mining.search_strategy import SearchStrategy  # noqa: E402
from ui.settings_store import DEFAULTS  # noqa: E402
from worker.controller import MiningController  # noqa: E402


def _sample_job(**kw) -> MiningJob:
    params = [
        kw.get("job_id", "j1"),
        "00" * 32,
        "aabb",
        "ccdd",
        [],
        "20000000",
        "1d00ffff",
        "5a000001",
        True,
    ]
    return job_from_notify(params, "abcd", 4, 1.0, 1)


def test_settings_default_strategy():
    assert DEFAULTS.get("mining_search_strategy") == "sequential"


def test_job_allocate_logical_reverse_and_random():
    job = _sample_job()
    job.configure_search_strategy(SearchStrategy.REVERSE, work_family_id="fam")
    b = job.allocate_batch(16)
    assert b is not None
    assert b.strategy == "reverse"
    assert b.logical_start == 0
    assert b.start_nonce == 0xFFFFFFFF
    job2 = _sample_job(job_id="j2")
    job2.configure_search_strategy(SearchStrategy.RANDOMIZED, work_family_id="fam")
    b2 = job2.allocate_batch(8)
    assert b2 is not None and b2.strategy == "randomized"
    assert b2.affine_a & 1 == 1
    assert b2.seed_fp


def test_controller_locks_strategy_mid_session():
    c = MiningController()
    c.set_search_strategy("reverse")
    assert c.search_strategy() == "reverse"
    c._search_strategy_locked = True
    c.set_search_strategy("randomized")
    assert c.search_strategy() == "reverse"  # blocked
    c._search_strategy_locked = False
    c.set_search_strategy("randomized")
    assert c.search_strategy() == "randomized"


def test_gpu_strategy_search_optional():
    try:
        from gpu.miner import GpuMiner
        from mining.bitcoin import DIFF1_TARGET, midstate_from_header
    except Exception:
        return
    try:
        g = GpuMiner(autotune_local=False)
    except Exception:
        return
    try:
        genesis = bytes.fromhex(
            "0100000000000000000000000000000000000000000000000000000000000000"
            "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
            "4b1e5e4a29ab5f49ffff001d1dac2b7c"
        )
        ms = midstate_from_header(genesis)
        for strat, a, b in ((0, 1, 0), (1, 1, 0), (2, 3, 5)):
            r = g.search(
                ms,
                genesis,
                DIFF1_TARGET,
                0 if strat != 1 else 0xFFFFFFFF,
                1024,
                track_best=True,
                strategy=strat,
                aff_a=a,
                aff_b=b,
            )
            assert r.scanned == 1024
            assert r.best_nonce is not None
    finally:
        g.close()
