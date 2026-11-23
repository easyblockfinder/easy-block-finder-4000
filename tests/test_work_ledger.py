"""Stratum Work Ledger — duplicate search-space detection (no GPU required)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from audit.work_ledger import StratumWorkLedger, mask_secret  # noqa: E402


def _job(**kw):
    base = dict(
        job_id="j1",
        prevhash="aa" * 32,
        coinb1="00112233deadbeef",
        coinb2="44556677",
        merkle_branches=["bb" * 32],
        version="20000000",
        nbits="1d00ffff",
        ntime="5a000001",
        extranonce1="abcd1234",
        extranonce2_size=4,
        extranonce2=0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_mask_secret():
    assert mask_secret("bc1qexactaddresshere000000000000") != "bc1qexactaddresshere000000000000"
    assert "***" in mask_secret("abcd1234")
    assert mask_secret("") == ""


def test_identical_work_different_job_id_is_counted_not_auto_duplicate_hashes():
    led = StratumWorkLedger()
    led.on_subscribe(session_id=1, extranonce1="abcd1234", extranonce2_size=4)
    led.on_notify(_job(job_id="A"), clean=True, session_id=1)
    led.on_notify(_job(job_id="B"), clean=False, session_id=1)
    m = led.metrics()
    assert m["identical_work_notifications"] == 1
    assert m["duplicate_attempts"] == 0  # no ranges scanned yet
    assert m["duplicate_rate_percent"] == 0.0


def test_partial_overlap_counts_duplicate_attempts():
    led = StratumWorkLedger()
    led.on_subscribe(session_id=1, extranonce1="en1aaa", extranonce2_size=4)
    led.on_notify(_job(job_id="A"), clean=True, session_id=1)
    led.on_batch_allocated(
        job_id="A",
        extranonce2_hex="00000000",
        start_nonce=0,
        count=1000,
        scanned=1000,
    )
    # New job same family → en2 again 00000000; overlapping range
    led.on_notify(_job(job_id="B"), clean=False, session_id=1)
    led.on_batch_allocated(
        job_id="B",
        extranonce2_hex="00000000",
        start_nonce=500,
        count=1000,
        scanned=1000,
    )
    m = led.metrics()
    assert m["total_attempts"] == 2000
    assert m["duplicate_attempts"] == 500
    assert m["estimated_unique_attempts"] == 1500
    assert m["duplicate_rate_percent"] == 25.0
    assert m["identical_work_notifications"] == 1


def test_exact_same_range_full_duplicate():
    led = StratumWorkLedger()
    led.on_subscribe(session_id=1, extranonce1="en1", extranonce2_size=4)
    led.on_notify(_job(job_id="A"), clean=True, session_id=1)
    led.on_batch_allocated("A", "00000000", 0, 8000, 8000)
    led.on_notify(_job(job_id="B"), clean=False, session_id=1)
    led.on_batch_allocated("B", "00000000", 0, 8000, 8000)
    m = led.metrics()
    assert m["duplicate_attempts"] == 8000
    assert m["estimated_unique_attempts"] == 8000
    assert m["duplicate_rate_percent"] == 50.0


def test_different_en2_not_duplicate():
    led = StratumWorkLedger()
    led.on_subscribe(session_id=1, extranonce1="en1", extranonce2_size=4)
    led.on_notify(_job(job_id="A"), clean=True, session_id=1)
    led.on_batch_allocated("A", "00000000", 0, 1000, 1000)
    led.on_batch_allocated("A", "00000001", 0, 1000, 1000)
    m = led.metrics()
    assert m["duplicate_attempts"] == 0
    assert m["estimated_unique_attempts"] == 2000


def test_reconnect_extranonce1_change():
    led = StratumWorkLedger()
    led.on_subscribe(session_id=1, extranonce1="aaaa", extranonce2_size=4)
    led.on_notify(_job(job_id="A", extranonce1="aaaa"), clean=True, session_id=1)
    led.on_subscribe(session_id=2, extranonce1="bbbb", extranonce2_size=4)
    m = led.metrics()
    assert m["reconnects"] == 1
    assert m["extranonce1_changes"] == 1


def test_aborted_inflight_and_job_duration():
    led = StratumWorkLedger()
    led.on_subscribe(session_id=1, extranonce1="en1", extranonce2_size=4)
    led.on_notify(_job(job_id="A"), clean=True, session_id=1)
    led.on_batch_allocated("A", "00000000", 0, 100, 100)
    led.on_inflight_aborted(1)
    led.on_notify(_job(job_id="B", ntime="5a000099"), clean=True, session_id=1)
    m = led.metrics()
    assert m["aborted_inflight_batches"] == 1
    assert m["jobs_seen"] >= 2


def test_best_timeline():
    led = StratumWorkLedger()
    led.on_gpu_best(1.5, "00" * 32)
    led.on_accepted_best(2.0, "11" * 32)
    m = led.metrics()
    assert len(m["gpu_best_timeline"]) == 1
    assert len(m["accepted_best_timeline"]) == 1
    assert m["gpu_best_timeline"][0]["difficulty"] == 1.5


def test_export_masks_secrets():
    led = StratumWorkLedger()
    led.on_subscribe(session_id=1, extranonce1="secreten1value", extranonce2_size=4)
    led.on_notify(
        _job(job_id="A", coinb1="0011deadbeefwalletish"),
        clean=True,
        session_id=1,
        payout_address="bc1qshouldbemasked000000000000000",
    )
    raw = led.export_dict(mask=True)
    blob = json.dumps(raw)
    assert "secreten1value" not in blob
    assert "bc1qshouldbemasked000000000000000" not in blob
    assert "deadbeefwalletish" not in blob or "***" in blob
    assert "work_family_id" in blob
    # unmasked path still available for local debug flag
    raw2 = led.export_dict(mask=False)
    assert "secreten1value" in json.dumps(raw2)


def test_changed_fields_recorded():
    led = StratumWorkLedger()
    led.on_subscribe(session_id=1, extranonce1="en1", extranonce2_size=4)
    led.on_notify(_job(job_id="A", ntime="11111111"), clean=True, session_id=1)
    led.on_notify(_job(job_id="B", ntime="22222222"), clean=False, session_id=1)
    ev = led.export_dict(mask=True)["notify_events"]
    assert ev[-1]["changed_fields"]  # at least ntime/job_id
    assert "ntime" in ev[-1]["changed_fields"] or "job_id" in ev[-1]["changed_fields"]


def test_attempts_use_scanned_not_allocated_count():
    led = StratumWorkLedger()
    led.on_subscribe(session_id=1, extranonce1="en1", extranonce2_size=4)
    led.on_notify(_job(job_id="A"), clean=True, session_id=1)
    led.on_gpu_batch_completed(
        job_id="A",
        work_family_id="",
        extranonce2_hex="00000000",
        start_nonce=0,
        allocated_count=10_000,
        scanned=2_500,
    )
    m = led.metrics()
    assert m["total_attempts"] == 2500
    assert m["unique_attempts"] == 2500
    assert m["measurement_source"] == "gpu_completed_batches"
    assert m["attempts_are_gpu_completed"] is True
    assert m["attempts_are_synthetic"] is False


def test_jobs_cut_by_notify_reported():
    led = StratumWorkLedger()
    led.on_subscribe(session_id=1, extranonce1="en1", extranonce2_size=4)
    led.on_notify(_job(job_id="A"), clean=True, session_id=1)
    led.on_batch_allocated("A", "00000000", 0, 100, 100)
    led.on_notify(_job(job_id="B", ntime="5a000099"), clean=False, session_id=1)
    m = led.metrics()
    assert m["jobs_cut_by_notify"] == 1
    assert m["hashes_completed_on_cut_jobs"] == 100


def test_synthetic_source_flagged():
    from audit.work_ledger import MEASUREMENT_SYNTHETIC

    led = StratumWorkLedger(measurement_source=MEASUREMENT_SYNTHETIC)
    m = led.metrics()
    assert m["attempts_are_synthetic"] is True
    assert m["attempts_are_gpu_completed"] is False
    assert "SYNTHETIC" in led.export_dict()["disclaimer"]


def test_overhead_and_hashrate_notes():
    led = StratumWorkLedger()
    led.note_overhead_s(0.001)
    led.note_hashrate(1.5e8)
    m = led.metrics()
    assert m["ledger_overhead_calls"] == 1
    assert m["hashrate_sample_count"] == 1
    assert m["hashrate_mean"] == 1.5e8
