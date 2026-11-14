"""clean_jobs in-flight, submit id esleme, nonce sinir, merkle regression protection."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.bitcoin import (  # noqa: E402
    bits_to_target,
    hash256,
    is_hash_below_target,
    merkle_root_to_header_bytes,
    share_target_from_difficulty,
)
from mining.job import MiningJob, job_from_notify  # noqa: E402
def _job(diff=1.0, en2_size=4) -> MiningJob:
    return job_from_notify(
        [
            "jobA",
            "00" * 32,
            "00",
            "00",
            [],
            "20000000",
            "1d00ffff",
            "5a000000",
            True,
        ],
        "abcd",
        en2_size,
        diff,
        1,
    )


def test_merkle_still_no_word_swap():
    """Kathisl edilmjob share akisi — merkle serwithstirmesi bozulmamali."""
    raw = hash256(b"\x00")
    assert merkle_root_to_header_bytes(raw) == raw


def test_clean_false_inflight_network_hit_kept():
    """
    GPU batch calisirken clean=false: old job superseded; snapshot with
    network hedefini snetworklayan candidate kaybolmaz (generation matchmez diye atilmaz).
    """
    from dataclasses import replace

    job = _job(diff=0.00000001)
    batch = job.allocate_batch(8000)
    assert batch is not None
    # Ag hedefini share with same easyliga cek — meets_network uret
    snap = replace(
        batch.snapshot,
        network_target_value=batch.snapshot.share_target_value,
    )

    job.mark_superseded()
    assert job.accept_new_work() is False
    assert job.submit_allowed() is True

    hit = None
    for n in range(batch.start_nonce, batch.start_nonce + min(batch.count, 8000)):
        verified = snap.verify_nonce(n)
        if verified and verified.get("meets_network"):
            hit = verified
            break
    assert hit is not None
    assert hit["meets_network"] is True
    assert hit["job_id"] == "jobA"
    # Canli job artik "en son generation" not; yine de snapshot gecerli
    assert job.generation != 99
    assert snap.verify_nonce(hit["nonce"]) is not None
    assert job.invalidated is False


def test_clean_true_inflight_submit_forbidden():
    job = _job(diff=0.00000001)
    batch = job.allocate_batch(2000)
    assert batch is not None
    snap = batch.snapshot
    job.mark_invalidated()
    assert job.submit_allowed() is False
    # allocate-time snap submit_forbidden False olabilir; controller job.invalidated bakar
    # invalidated afreandrsei new snap:
    assert job.snapshot().submit_forbidden is True
    assert job.snapshot().verify_nonce(batch.start_nonce) is None


def test_allocate_boundary_no_skip_no_dup():
    job = _job(en2_size=2)
    job.nonce = 0xFFFFFFFC
    job.extranonce2 = 5
    mid0 = job._midstate
    b1 = job.allocate_batch(16)
    assert b1 is not None
    assert b1.start_nonce == 0xFFFFFFFC
    assert b1.count == 4
    assert b1.snapshot.extranonce2_hex == "0005"
    assert b1.snapshot.midstate == mid0
    # Ayni (header, nonce) interval tekrar andrilmemeli
    b2 = job.allocate_batch(16)
    assert b2 is not None
    assert b2.snapshot.extranonce2_hex == "0006"
    assert b2.start_nonce == 0
    assert set(range(b1.start_nonce, b1.start_nonce + b1.count)).isdisjoint(
        range(b2.start_nonce, b2.start_nonce + b2.count)
    ) or b1.snapshot.extranonce2_hex != b2.snapshot.extranonce2_hex


def test_submit_result_matches_by_request_id(isolated_controller):
    ctrl = isolated_controller()
    ctrl.address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    e1 = {
        "pending": True,
        "job_id": "j1",
        "nonce_hex": "11111111",
        "submit_id": 10,
        "session_id": 1,
        "block_candidate": False,
    }
    e2 = {
        "pending": True,
        "job_id": "j2",
        "nonce_hex": "22222222",
        "submit_id": 11,
        "session_id": 1,
        "block_candidate": True,
        "hash": "00" * 32,
        "test_mode": True,
    }
    with ctrl._submit_lock:
        ctrl._pending_submits[(1, 10)] = e1
        ctrl._pending_submits[(1, 11)] = e2

    # Ters order: before 11
    ctrl._on_submit_result(
        True,
        "accepted",
        {"id": 11, "session_id": 1, "result": True, "error": None},
    )
    assert e2["pending"] is False
    assert e1["pending"] is True
    assert ctrl.stats.accepted == 1

    ctrl._on_submit_result(
        False,
        "rejected: x",
        {"id": 10, "session_id": 1, "result": False, "error": [23, "Above target"]},
    )
    assert e1["pending"] is False
    assert "rejected" in e1["status"]
    assert ctrl.stats.rejected == 1
    assert ctrl.stats.accepted == 1  # did not increase


def test_submit_error_none_result_true_only_counts(isolated_controller):
    ctrl = isolated_controller()
    e = {"pending": True, "submit_id": 5, "session_id": 2, "job_id": "j", "nonce_hex": "aa"}
    with ctrl._submit_lock:
        ctrl._pending_submits[(2, 5)] = e
    ctrl._on_submit_result(
        True,
        "accepted",
        {"id": 5, "session_id": 2, "result": True, "error": ["oops"]},
    )
    # error dolu → accepted sayilmaz
    assert ctrl.stats.accepted == 0
    assert ctrl.stats.rejected == 1


def test_submit_race_register_before_send_id(isolated_controller):
    """Kayit, response gelmeden before (session,id) with hazir olmali."""
    ctrl = isolated_controller()
    entry = {"pending": True, "job_id": "j", "nonce_hex": "00", "submit_id": 99, "session_id": 3}
    with ctrl._submit_lock:
        ctrl._pending_submits[(3, 99)] = entry
    # Ymomentt submit_share return etmeden before
    ctrl._on_submit_result(
        True, "accepted", {"id": 99, "session_id": 3, "result": True, "error": None}
    )
    assert entry["pending"] is False
    assert ctrl.stats.accepted == 1


def test_wrong_session_ignored(isolated_controller):
    ctrl = isolated_controller()
    e = {"pending": True, "submit_id": 1, "session_id": 1, "job_id": "j", "nonce_hex": "00"}
    with ctrl._submit_lock:
        ctrl._pending_submits[(1, 1)] = e
    ctrl._on_submit_result(
        True, "accepted", {"id": 1, "session_id": 99, "result": True, "error": None}
    )
    assert e["pending"] is True
    assert ctrl.stats.accepted == 0


def test_accepted_share_does_not_overwrite_last_block(isolated_controller):
    """Normal accepted share, submit_id/session cakissa eandn Son block candidateni degjobtirmez."""
    ctrl = isolated_controller()
    block_hash = "ab" * 32
    last_block = {
        "block_candidate": True,
        "hash": block_hash,
        "submit_id": 7,
        "session_id": 1,
        "status": "aday_bulundu",
        "nonce_hex": "deadbeef",
        "job_id": "oldjob",
    }
    ctrl.stats.last_block = dict(last_block)
    ctrl.stats.block_candidates = [dict(last_block)]

    # Ayni submit_id/session — orderdan share (block not)
    share = {
        "pending": True,
        "block_candidate": False,
        "hash": "cd" * 32,
        "submit_id": 7,
        "session_id": 1,
        "job_id": "sharejob",
        "nonce_hex": "11111111",
        "status": "share — sending (reward not)",
    }
    with ctrl._submit_lock:
        ctrl._pending_submits[(1, 7)] = share

    ctrl._on_submit_result(
        True,
        "accepted",
        {"id": 7, "session_id": 1, "result": True, "error": None},
    )
    assert ctrl.stats.accepted == 1
    assert ctrl.stats.last_block["hash"] == block_hash
    assert ctrl.stats.last_block["status"] == "aday_bulundu"
    assert ctrl.stats.last_block["nonce_hex"] == "deadbeef"


def test_block_submit_result_requires_hash_match(isolated_controller):
    """Blok responsei: hash uyusmazsa last_block guncellenmez (old/new kimlik cakismasi)."""
    ctrl = isolated_controller()
    ctrl.stats.last_block = {
        "block_candidate": True,
        "hash": "11" * 32,
        "submit_id": 3,
        "session_id": 2,
        "status": "aday_bulundu",
        "nonce_hex": "aaaaaaaa",
    }
    other = {
        "pending": True,
        "block_candidate": True,
        "hash": "22" * 32,  # different hash, same id/session
        "submit_id": 3,
        "session_id": 2,
        "job_id": "j2",
        "nonce_hex": "bbbbbbbb",
        "test_mode": True,
    }
    with ctrl._submit_lock:
        ctrl._pending_submits[(2, 3)] = other
    ctrl._on_submit_result(
        True,
        "accepted",
        {"id": 3, "session_id": 2, "result": True, "error": None},
    )
    assert ctrl.stats.last_block["hash"] == "11" * 32
    assert ctrl.stats.last_block["status"] == "aday_bulundu"


def test_matching_block_candidate_updates_last_block(isolated_controller):
    ctrl = isolated_controller()
    h = "33" * 32
    entry = {
        "pending": True,
        "block_candidate": True,
        "hash": h,
        "submit_id": 5,
        "session_id": 4,
        "job_id": "bj",
        "nonce_hex": "cccccccc",
        "status": "aday_bulundu",
        "test_mode": True,
    }
    ctrl.stats.last_block = dict(entry)
    ctrl.stats.block_candidates = [dict(entry)]
    with ctrl._submit_lock:
        ctrl._pending_submits[(4, 5)] = entry
    ctrl._on_submit_result(
        True,
        "accepted",
        {"id": 5, "session_id": 4, "result": True, "error": None},
    )
    assert ctrl.stats.last_block["hash"] == h
    assert "accepted" in ctrl.stats.last_block["status"]
    assert ctrl.stats.block_candidates[0]["hash"] == h
    assert "accepted" in ctrl.stats.block_candidates[0]["status"]
