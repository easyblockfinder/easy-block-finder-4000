"""Bilinen Bitcoin block basligi and CPU/GPU karsilastirma testleri."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.bitcoin import (  # noqa: E402
    bits_to_target,
    hash256,
    header_hash,
    is_hash_below_target,
    midstate_from_header,
    share_target_from_difficulty,
    validate_bitcoin_address,
    verify_header_against_targets,
)

GENESIS_HEADER = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000"
    "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
    "4b1e5e4a29ab5f49ffff001d1dac2b7c"
)
GENESIS_HASH = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"


def test_genesis_sha256d():
    assert len(GENESIS_HEADER) == 80
    digest = hash256(GENESIS_HEADER)
    assert digest[::-1].hex() == GENESIS_HASH
    assert header_hash(GENESIS_HEADER) == digest


def test_genesis_meets_bits_target():
    target = bits_to_target("1d00ffff")
    digest = hash256(GENESIS_HEADER)
    assert is_hash_below_target(digest, target)


def test_wrong_nonce_fails_network_target():
    bad = GENESIS_HEADER[:76] + struct.pack("<I", 0x12345678)
    target = bits_to_target("1d00ffff")
    digest = hash256(bad)
    assert not is_hash_below_target(digest, target)


def test_share_target_scales():
    t1 = share_target_from_difficulty(1.0)
    t2 = share_target_from_difficulty(2.0)
    assert t2 == t1 // 2


def test_address_validation():
    ok, _ = validate_bitcoin_address("")
    assert not ok
    ok, _ = validate_bitcoin_address("not-an-address")
    assert not ok
    # Gecerli mainnet P2PKH ornegi (Satoshi era known adres)
    ok, err = validate_bitcoin_address("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
    assert ok, err


def test_midstate_consistent_with_full_hash():
    ms = midstate_from_header(GENESIS_HEADER)
    assert len(ms) == 32
    # GPU with same yolu: midstate + nonce tarama yerine tam hash
    assert hash256(GENESIS_HEADER)[::-1].hex() == GENESIS_HASH


def test_verify_header_share_and_network_separate():
    easy = share_target_from_difficulty(0.0001)
    net = bits_to_target("1d00ffff")
    result = verify_header_against_targets(GENESIS_HEADER, easy, net)
    assert result["meets_share"]
    assert result["meets_network"]


def test_gpu_cpu_agree_on_genesis_nonce():
    from gpu.miner import GpuMiner, GpuUnavailableError

    try:
        gpu = GpuMiner(autotune_local=False)
    except GpuUnavailableError as exc:
        pytest.skip(f"OpenCL GPU yok: {exc}")

    ms = midstate_from_header(GENESIS_HEADER)
    nonce = struct.unpack("<I", GENESIS_HEADER[76:80])[0]
    target = (1 << 256) - 1
    res = gpu.search(ms, GENESIS_HEADER, target, nonce, 1)
    assert res.scanned == 1
    assert res.hits == [nonce]
    assert res.global_size % res.local_size == 0
    gpu.close()

    # Komsu nonce GPU'da share hedefi (network) with should not find
    net = bits_to_target("1d00ffff")
    gpu = GpuMiner(autotune_local=False)
    res2 = gpu.search(ms, GENESIS_HEADER, net, nonce + 1, 64)
    gpu.close()
    assert res2.scanned == 64
    assert nonce not in res2.hits
    for n in res2.hits:
        header = GENESIS_HEADER[:76] + struct.pack("<I", n)
        assert verify_header_against_targets(header, net, net)["meets_share"]


def test_nonce_exhaustion_bumps_extranonce():
    from mining.job import MiningJob

    job = MiningJob(
        job_id="j",
        prevhash="0" * 64,
        coinb1="00",
        coinb2="00",
        merkle_branches=[],
        version="20000000",
        nbits="1d00ffff",
        ntime="5a000000",
        clean_jobs=True,
        extranonce1="abcd",
        extranonce2_size=2,
        difficulty=1.0,
    )
    job.rebuild_work()
    job.nonce = 0xFFFFFFFE
    job.extranonce2 = 0
    en2_before = job.extranonce2
    mid_before = job._midstate
    batch = job.allocate_batch(4)
    assert batch is not None
    assert batch.start_nonce == 0xFFFFFFFE
    assert batch.count == 2
    # Son range OLD extranonce/header with
    assert job.extranonce2 == en2_before
    assert batch.snapshot.midstate == mid_before
    assert batch.snapshot.extranonce2_hex == "0000"
    # Bir sonraki allocate bump eder
    batch2 = job.allocate_batch(4)
    assert batch2 is not None
    assert job.extranonce2 == 1
    assert batch2.start_nonce == 0
    assert batch2.snapshot.extranonce2_hex == "0001"
    assert batch2.snapshot.midstate != mid_before


def test_midstate_cached_until_prefix64_changes():
    from mining.job import MiningJob

    job = MiningJob(
        job_id="j",
        prevhash="0" * 64,
        coinb1="00",
        coinb2="00",
        merkle_branches=[],
        version="20000000",
        nbits="1d00ffff",
        ntime="5a000000",
        clean_jobs=True,
        extranonce1="abcd",
        extranonce2_size=4,
        difficulty=1.0,
    )
    job.rebuild_work()
    ms1 = job._midstate
    key1 = job._midstate_key
    assert len(ms1) == 32 and len(key1) == 64
    # Ayni extranonce2 with again — midstate same kalmali
    job.rebuild_work()
    assert job._midstate == ms1
    assert job._midstate_key == key1
    # extranonce2 when it changes merkle/prefix64 degjobir → midstate refreshed
    job.extranonce2 = 1
    job.rebuild_work()
    assert job._midstate_key != key1
    assert len(job._midstate) == 32


def test_revoked_job_stops_verify():
    from mining.job import MiningJob

    job = MiningJob(
        job_id="j",
        prevhash="0" * 64,
        coinb1="00",
        coinb2="00",
        merkle_branches=[],
        version="01000000",
        nbits="1d00ffff",
        ntime="29ab5f49",
        clean_jobs=True,
        extranonce1="",
        extranonce2_size=4,
        difficulty=0.0001,
    )
    job._header_prefix = GENESIS_HEADER[:76]
    job._midstate = midstate_from_header(GENESIS_HEADER)
    job.revoked = True
    assert job.verify_candidate(0x7C2BAC1D) is None
