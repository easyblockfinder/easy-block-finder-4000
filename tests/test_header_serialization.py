"""Stratum/Bitcoin header serwithstirme — merkle swap regressionu and submit rethisild."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.bitcoin import (  # noqa: E402
    build_block_header,
    build_coinbase,
    build_merkle_root,
    hash256,
    is_hash_below_target,
    merkle_root_to_header_bytes,
    nonce_from_submit_hex,
    nonce_to_submit_hex,
    rebuild_header_from_submit,
    share_target_from_difficulty,
    stratum_prevhash_to_header_bytes,
)
from mining.job import MiningJob, job_from_notify  # noqa: E402

# Genesis coinbase (tek tx) → merkle root header almoment = hash256(coinbase), swap YOK
GENESIS_COINBASE = bytes.fromhex(
    "01000000010000000000000000000000000000000000000000000000000000000000000000"
    "ffffffff4d04ffff001d0104455468652054696d65732030332f4a616e2f3230303920436861"
    "6e63656c6c6f72206f6e206272696e6b206f66207365636f6e64206261696c6f757420666f72"
    "2062616e6b73ffffffff0100f2052a01000000434104678afdb0fe5548271967f1a67130b710"
    "5cd6a828e03909a67962e0ea1f61deb649f6bc3f4cef38c4f35504e51ec112de5c384df7ba0b"
    "8d578a4c702b6bf11d5fac00000000"
)
GENESIS_MERKLE_HEADER = bytes.fromhex(
    "3ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a"
)


def test_merkle_root_no_word_swap_vs_genesis():
    mh = hash256(GENESIS_COINBASE)
    assert mh == GENESIS_MERKLE_HEADER
    assert merkle_root_to_header_bytes(mh) == GENESIS_MERKLE_HEADER
    # Eski errorli 4-bayt swap this andctor would break
    wrong = b"".join(mh[i : i + 4][::-1] for i in range(0, 32, 4))
    assert wrong != GENESIS_MERKLE_HEADER


def test_stratum_prevhash_word_swap_stackexchange():
    # https://bitcoin.stackexchange.com/questions/92705
    received = "4128bf630f57387b00e25b419d1bb77e667e4036a7d8fee80000015600000000"
    expected = bytes.fromhex(
        "63bf28417b38570f415be2007eb71b9d36407e66e8fed8a75601000000000000"
    )
    assert stratum_prevhash_to_header_bytes(received) == expected


def test_header_build_merkle_as_is_with_prev_swap():
    prev = "4128bf630f57387b00e25b419d1bb77e667e4036a7d8fee80000015600000000"
    merkle = bytes.fromhex(
        "9b9c9ab0b1c92844e4fed3f895f9443fefcda5ae02cc5a8ad4444f9303081a23"
    )
    header = build_block_header(
        "20000000", prev, merkle, "5e148a8c", "1a02b098", 0xD0CF1040
    )
    assert header[:4] == bytes.fromhex("00000020")
    assert header[4:36] == stratum_prevhash_to_header_bytes(prev)
    assert header[36:68] == merkle  # swap yok
    assert header[68:72] == bytes.fromhex("8c8a145e")
    assert header[72:76] == bytes.fromhex("98b0021a")
    # nonce submit hex "d0cf1040" → int 0xd0cf1040 → header LE baytlari
    assert header[76:80] == (0xD0CF1040).to_bytes(4, "little")
    assert header[76:80] == bytes.fromhex("4010cfd0")


def test_nonce_submit_identity():
    for n in (0, 1, 0xAD36D76A, 0x7FF66870, 0x202A3705, 0xFFFFFFFF):
        hx = nonce_to_submit_hex(n)
        assert len(hx) == 8
        assert nonce_from_submit_hex(hx) == n
        # Header LE baytlari same tamsayiyi tasir
        assert int.from_bytes(bytes.fromhex(hx), "big") == n


def test_rebuild_from_submit_matches_job_buffer():
    job = MiningJob(
        job_id="6af4689e00000636",
        prevhash="4128bf630f57387b00e25b419d1bb77e667e4036a7d8fee80000015600000000",
        coinb1="01000000010000000000000000000000000000000000000000000000000000000000000000"
        "ffffffff3503",
        coinb2="0c2f736c7573682f000000000100000000000000001976a914000000000000000000000000"
        "00000000000088ac00000000",
        merkle_branches=[
            "12ae2555f80b865bac89fa3aeb4df41b730422670fb80d1a0536276b481fab53",
        ],
        version="20000000",
        nbits="1a02b098",
        ntime="5e148a8c",
        clean_jobs=True,
        extranonce1="aabb",
        extranonce2_size=4,
        difficulty=1.0,
    )
    job.extranonce2 = 0x01020304
    job.rebuild_work()
    nonce = 0xAD36D76A
    buffered = job.header_for_nonce(nonce)
    rebuilt = rebuild_header_from_submit(
        version_hex=job.version,
        prevhash_hex=job.prevhash,
        coinb1_hex=job.coinb1,
        coinb2_hex=job.coinb2,
        merkle_branches=job.merkle_branches,
        extranonce1_hex=job.extranonce1,
        extranonce2_hex=job.extranonce2_hex(),
        ntime_hex=job.ntime,
        nbits_hex=job.nbits,
        nonce_hex=nonce_to_submit_hex(nonce),
    )
    assert rebuilt["header"] == buffered
    assert rebuilt["nonce"] == nonce
    assert rebuilt["merkle_root"] == job._merkle_root


def test_job_snapshot_difficulty_frozen():
    params = [
        "job1",
        "00" * 32,
        "00",
        "00",
        [],
        "20000000",
        "1d00ffff",
        "5a000000",
        True,
    ]
    job = job_from_notify(params, "abcd", 4, difficulty=1.0, generation=1)
    snap = job.snapshot()
    job.difficulty = 999.0  # actiand job if it changes eandn
    assert snap.difficulty == 1.0
    assert snap.share_target() == share_target_from_difficulty(1.0)


def test_notify_diff_then_set_difficulty_updates_work_not_notify_mark():
    """
    CKPool ordersi: notify ordersinda diff=10000, after set_difficulty=1.
    diff_at_notify=10000 kalir; calisma difficulty and afterki batch snapshot=1.
    Notify moment share lock is not.
    """
    params = [
        "6af4689e0000064d",
        "00" * 32,
        "00",
        "00",
        [],
        "20000000",
        "1d00ffff",
        "5a000000",
        True,
    ]
    job = job_from_notify(params, "abcd", 4, difficulty=10000.0, generation=1)
    assert job.diff_at_notify == 10000.0
    assert job.difficulty == 10000.0

    # Stratum set_difficulty(1) — controller'in yaptigi like
    job.difficulty = 1.0
    assert job.diff_at_notify == 10000.0  # notify marker fixed
    assert job.difficulty == 1.0

    batch = job.snapshot()
    assert batch.difficulty == 1.0
    assert batch.diff_at_notify == 10000.0
    assert batch.share_target() == share_target_from_difficulty(1.0)


def test_verify_candidate_uses_independent_rebuild():
    job = MiningJob(
        job_id="j",
        prevhash="00" * 32,
        coinb1="00",
        coinb2="00",
        merkle_branches=[],
        version="20000000",
        nbits="1d00ffff",
        ntime="5a000000",
        clean_jobs=True,
        extranonce1="00",
        extranonce2_size=4,
        difficulty=0.00000001,  # cok easy — almost eandry nonce
    )
    job.rebuild_work()
    batch_snap = job.snapshot()
    hit = None
    for n in range(0, 5000):
        h = job.header_for_nonce(n)
        if is_hash_below_target(hash256(h), batch_snap.share_target()):
            hit = n
            break
    assert hit is not None
    verified = job.verify_candidate(hit, snapshot=batch_snap)
    assert verified is not None
    assert verified["buffer_header_match"] is True
    assert verified["nonce_hex"] == nonce_to_submit_hex(hit)
    assert verified["rebuild"]["header"] == job.header_for_nonce(hit)
    assert verified["difficulty"] == 0.00000001
    # Aktif job zorlugu if it changes eandn batch snapshot with andrification same kalir
    job.difficulty = 1e9
    verified2 = job.verify_candidate(hit, snapshot=batch_snap)
    assert verified2 is not None
    assert verified2["difficulty"] == 0.00000001


def test_wrong_merkle_swap_breaks_rebuild_equality():
    """Kmomentt: old 4-bayt merkle swap, independent rethisild with thisffer breaks."""
    coinbase = build_coinbase("00", "aa", b"\x00\x00\x00\x01", "00")
    merkle = build_merkle_root(coinbase, [])
    correct = build_block_header(
        "20000000", "00" * 32, merkle, "5a000000", "1d00ffff", 1
    )
    swapped = b"".join(merkle[i : i + 4][::-1] for i in range(0, 32, 4))
    wrong = (
        correct[:36]
        + swapped
        + correct[68:]
    )
    assert correct != wrong
    assert merkle_root_to_header_bytes(merkle) == merkle
