"""Live audit observer unit tests (no GPU required)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from audit.histogram import HistogramResult  # noqa: E402
from audit.live_observer import LiveAuditObserver  # noqa: E402
from audit.work_family import work_family_id  # noqa: E402


def test_work_family_ignores_job_id():
    a = work_family_id(
        prevhash="aa",
        coinb1="01",
        coinb2="02",
        merkle_branches=["bb"],
        version="20000000",
        nbits="1d00ffff",
        ntime="1",
        extranonce1="ee",
        extranonce2_size=4,
    )
    b = work_family_id(
        prevhash="aa",
        coinb1="01",
        coinb2="02",
        merkle_branches=["bb"],
        version="20000000",
        nbits="1d00ffff",
        ntime="1",
        extranonce1="ee",
        extranonce2_size=4,
    )
    assert a == b


def test_identical_notify_detected():
    obs = LiveAuditObserver()
    job = SimpleNamespace(
        prevhash="00" * 32,
        coinb1="00",
        coinb2="00",
        merkle_branches=[],
        version="20000000",
        nbits="1d00ffff",
        ntime="5a000000",
        extranonce1="abcd",
        extranonce2_size=4,
        extranonce2=0,
    )
    obs.on_notify(job, False)
    obs.on_notify(job, False)
    snap = obs.snapshot()
    assert snap.identical_notify_count == 1


def test_duplicate_range_count():
    obs = LiveAuditObserver()
    hist = HistogramResult(counts=[1] * 12, attempts=10)
    result = SimpleNamespace(truncated=False, best_hash_be_hex=None, best_nonce=None)
    kwargs = dict(
        family_id="f1",
        extranonce2_hex="00000000",
        header_prefix=b"\0" * 76,
        start_nonce=0,
        count=10,
        result=result,
        hist=hist,
        t0=0.0,
    )
    obs.on_batch(**kwargs)
    obs.on_batch(**kwargs)
    snap = obs.snapshot()
    assert snap.duplicate_range_count == 1
    assert snap.attempts == 20
    assert snap.unique_attempts == 10
