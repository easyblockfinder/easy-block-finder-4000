"""GPU batch-best tracking vs CPU minimum (skips without OpenCL GPU)."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from gpu.miner import GpuMiner, GpuUnavailableError, SearchResult  # noqa: E402
from mining.best_hash import hash_be_hex_to_int  # noqa: E402
from mining.bitcoin import hash256, midstate_from_header  # noqa: E402

GENESIS = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000"
    "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
    "4b1e5e4a29ab5f49ffff001d1dac2b7c"
)
IMPOSSIBLE_TARGET = 1  # no share hits; best must still be reported


def _cpu_best(start: int, count: int) -> tuple[int, int, bytes]:
    best = None
    for n in range(start, start + count):
        d = hash256(GENESIS[:76] + struct.pack("<I", n))
        v = int.from_bytes(d, "little")
        if best is None or v < best[0]:
            best = (v, n, d)
    return best


@pytest.fixture(scope="module")
def gpu():
    try:
        g = GpuMiner(autotune_local=False)
    except GpuUnavailableError as exc:
        pytest.skip(str(exc))
    yield g
    g.close()


@pytest.mark.parametrize("start,count", [(0, 256), (1000, 1000), (0xFFFFF000, 777), (5, 60000)])
def test_batch_best_matches_cpu_min(gpu, start, count):
    ms = midstate_from_header(GENESIS)
    r = gpu.search(ms, GENESIS, IMPOSSIBLE_TARGET, start, count, track_best=True)
    _, nonce, digest = _cpu_best(start, count)
    assert r.best_nonce == nonce
    assert r.best_hash_be == digest
    assert r.best_hash_be_hex == digest[::-1].hex()


def test_track_best_false_returns_none(gpu):
    ms = midstate_from_header(GENESIS)
    r = gpu.search(ms, GENESIS, IMPOSSIBLE_TARGET, 0, 256, track_best=False)
    assert r.best_hash_be is None and r.best_nonce is None


def test_search_result_best_hash_be_hex_convention():
    # Genesis header: explorer hash starts with 000000000019d668...
    d = hash256(GENESIS)
    sr = SearchResult([], 1, 1, 256, 0, best_hash_be=d, best_nonce=0x1DAC2B7C)
    assert sr.best_hash_be_hex == d[::-1].hex()
    assert sr.best_hash_be_hex.startswith("000000000019d668")
    assert hash_be_hex_to_int(sr.best_hash_be_hex) == int.from_bytes(d, "little")
    assert sr.best_hash_int == int.from_bytes(d, "little")
    assert SearchResult([], 0, 0, 256, 0).best_hash_be_hex is None
    assert SearchResult([], 0, 0, 256, 0).best_hash_int is None


@pytest.mark.parametrize("ls", [0, 96, 1024])
def test_track_best_rejects_bad_local_size(ls):
    g = object.__new__(GpuMiner)
    g._local_size = ls
    with pytest.raises(ValueError, match="track_best"):
        g.search(b"\0" * 32, GENESIS, 1, 0, 16, track_best=True)
