"""GPU hash_nonces: real OpenCL output vs independent CPU SHA-256d."""

from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from gpu.miner import GpuMiner, GpuUnavailableError  # noqa: E402
from mining.bitcoin import header_hash, midstate_from_header  # noqa: E402

GENESIS = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000"
    "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
    "4b1e5e4a29ab5f49ffff001d1dac2b7c"
)


def test_gpu_hash_nonces_match_cpu_100():
    try:
        gpu = GpuMiner(autotune_local=False)
    except GpuUnavailableError as exc:
        pytest.skip(str(exc))

    ms = midstate_from_header(GENESIS)
    rng = random.Random(42)
    nonces = [rng.randrange(0, 0xFFFFFFFF) for _ in range(100)]
    digests = gpu.hash_nonces(ms, GENESIS, nonces)
    gpu.close()
    assert len(digests) == 100
    for i, nonce in enumerate(nonces):
        hdr = GENESIS[:76] + struct.pack("<I", nonce)
        cpu = header_hash(hdr)
        assert digests[i] == cpu, f"nonce={nonce:08x}"
