"""GPU audit histogram vs CPU reference; production kernel untouched equivalence."""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from audit.histogram import cpu_histogram_for_range  # noqa: E402
from audit.thresholds import AUDIT_DIFFICULTY_THRESHOLDS  # noqa: E402
from gpu.miner import GpuMiner, GpuUnavailableError  # noqa: E402
from mining.bitcoin import hash256, midstate_from_header  # noqa: E402

GENESIS = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000"
    "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
    "4b1e5e4a29ab5f49ffff001d1dac2b7c"
)
IMPOSSIBLE_TARGET = 1


@pytest.fixture(scope="module")
def gpu():
    try:
        g = GpuMiner(autotune_local=False)
    except GpuUnavailableError as exc:
        pytest.skip(f"OpenCL GPU unavailable: {exc}")
    if not g.ensure_audit_kernel():
        pytest.skip(f"Audit kernel unavailable: {g._audit_error}")
    yield g
    g.close()


def test_production_sha256d_cl_unchanged():
    """Guard: production kernel file must stay the mining-only source."""
    prod = (ROOT / "gpu" / "sha256d.cl").read_text(encoding="utf-8")
    assert "sha256d_search_audit" not in prod
    assert "AUDIT_N" not in prod
    assert "__kernel void sha256d_search(" in prod
    audit = (ROOT / "gpu" / "sha256d_audit.cl").read_text(encoding="utf-8")
    assert "sha256d_search_audit" in audit
    assert "AUDIT_N" in audit


@pytest.mark.parametrize("start,count", [(0, 256), (1000, 512), (0xFFFFF000, 128)])
def test_gpu_histogram_matches_cpu(gpu, start, count):
    ms = midstate_from_header(GENESIS)
    _result, hist = gpu.search_audit(
        ms, GENESIS, IMPOSSIBLE_TARGET, start, count, track_best=True
    )
    ref = cpu_histogram_for_range(GENESIS[:76], start, count)
    assert hist.attempts == count == ref.attempts
    assert hist.counts == ref.counts
    assert hist.overflow is False


def test_gpu_best_matches_cpu_best_separately(gpu):
    """Requirement 7: GPU best vs CPU best (separate from histogram)."""
    start, count = 0, 2048
    ms = midstate_from_header(GENESIS)
    result, _hist = gpu.search_audit(
        ms, GENESIS, IMPOSSIBLE_TARGET, start, count, track_best=True
    )
    best = None
    for n in range(start, start + count):
        d = hash256(GENESIS[:76] + struct.pack("<I", n))
        v = int.from_bytes(d, "little")
        if best is None or v < best[0]:
            best = (v, n, d)
    assert result.best_nonce == best[1]
    assert result.best_hash_be == best[2]


def test_production_and_audit_sha256d_digest_equivalence(gpu):
    """Requirement 8: normal hash_nonces digests match hashlib (audit uses same SHA)."""
    ms = midstate_from_header(GENESIS)
    nonces = [0, 1, 7, 100, 0x1DAC2B7C]
    digests = gpu.hash_nonces(ms, GENESIS, nonces)
    assert len(digests) == len(nonces)
    for n, d in zip(nonces, digests):
        expect = hashlib.sha256(
            hashlib.sha256(GENESIS[:76] + struct.pack("<I", n)).digest()
        ).digest()
        assert d == expect == hash256(GENESIS[:76] + struct.pack("<I", n))


def test_search_without_audit_still_works(gpu):
    """Production search path remains usable (audit off path)."""
    ms = midstate_from_header(GENESIS)
    r = gpu.search(ms, GENESIS, IMPOSSIBLE_TARGET, 0, 256, track_best=True)
    assert r.scanned == 256
    assert r.best_nonce is not None


def test_padding_not_counted_in_histogram(gpu):
    """Non-multiple of local_size: attempts == count, not global_size."""
    ms = midstate_from_header(GENESIS)
    count = 100  # not power-of-two fill
    result, hist = gpu.search_audit(
        ms, GENESIS, IMPOSSIBLE_TARGET, 0, count, track_best=False
    )
    assert result.scanned == count
    assert result.global_size >= count
    ref = cpu_histogram_for_range(GENESIS[:76], 0, count)
    assert hist.counts == ref.counts
    assert hist.attempts == count


def test_threshold_list_includes_focus_diffs():
    assert AUDIT_DIFFICULTY_THRESHOLDS.index(4200.0) >= 0
    assert AUDIT_DIFFICULTY_THRESHOLDS.index(5000.0) >= 0
    assert AUDIT_DIFFICULTY_THRESHOLDS.index(10000.0) >= 0
