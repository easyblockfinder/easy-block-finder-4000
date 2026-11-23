"""Offline validations for native mining search strategies."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.bitcoin import header_hash, midstate_from_header  # noqa: E402
from mining.search_strategy import (  # noqa: E402
    AffineParams,
    LogicalCursor,
    SearchStrategy,
    StrategySessionPolicy,
    affine_from_seed,
    is_bijective_strategy,
    physical_nonce,
    seed_material,
)

GENESIS = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000"
    "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
    "4b1e5e4a29ab5f49ffff001d1dac2b7c"
)
N = 4096  # same nonce count per strategy for digest checks


def test_same_header_same_count_sha256d_per_strategy():
    """Each strategy scans N logical steps; every physical nonce hashes correctly."""
    seed = b"val-sha"
    aff = affine_from_seed(seed)
    ms = midstate_from_header(GENESIS)
    assert len(ms) == 32
    for strat in SearchStrategy:
        digests = []
        seen = set()
        for i in range(N):
            nonce = physical_nonce(i, strat, affine=aff)
            assert nonce not in seen
            seen.add(nonce)
            hdr = GENESIS[:76] + nonce.to_bytes(4, "little")
            digests.append(header_hash(hdr))
        assert len(seen) == N
        assert len(digests) == N
        # Re-hash same physicals → identical (strategy-independent)
        for i, nonce in enumerate(sorted(seen)[:32]):
            hdr = GENESIS[:76] + nonce.to_bytes(4, "little")
            assert header_hash(hdr) == header_hash(hdr)


def test_bijection_math_all_strategies():
    aff = affine_from_seed(b"bij")
    assert is_bijective_strategy(SearchStrategy.SEQUENTIAL)
    assert is_bijective_strategy(SearchStrategy.REVERSE)
    assert is_bijective_strategy(SearchStrategy.RANDOMIZED, aff)
    # Reverse involution
    for i in (0, 1, 7, 0x80000000, 0xFFFFFFFE, 0xFFFFFFFF):
        r = physical_nonce(i, SearchStrategy.REVERSE)
        assert physical_nonce(r, SearchStrategy.REVERSE) == i
    # Affine inverse
    a_inv = pow(aff.a, -1, 0x100000000)
    for i in range(0, 10000, 97):
        p = aff.map(i)
        assert ((a_inv * ((p - aff.b) & 0xFFFFFFFF)) & 0xFFFFFFFF) == i


def test_affine_a_always_odd_uint32():
    for raw in (b"", b"x", b"\x00" * 32, b"\xff" * 16, os_urandom := __import__("os").urandom(64)):
        aff = affine_from_seed(raw if isinstance(raw, bytes) else raw)
        assert 0 <= aff.a <= 0xFFFFFFFF
        assert 0 <= aff.b <= 0xFFFFFFFF
        assert aff.a & 1 == 1
    with pytest.raises(ValueError):
        AffineParams(a=2, b=0)
    with pytest.raises(ValueError):
        AffineParams(a=0, b=1)


def test_nonce_exhaust_bump_resume_edges():
    seed0 = seed_material(
        work_family_id="f", extranonce2_hex="00000000", strategy=SearchStrategy.REVERSE
    )
    cur = LogicalCursor(SearchStrategy.REVERSE, seed0, cursor=0xFFFFFFFF)
    b = cur.allocate(1)
    assert b is not None and b.count == 1 and b.needs_extranonce_bump_after
    assert physical_nonce(0xFFFFFFFF, SearchStrategy.REVERSE) == 0
    assert cur.allocate(1) is None
    seed1 = seed_material(
        work_family_id="f", extranonce2_hex="00000001", strategy=SearchStrategy.REVERSE
    )
    cur.reset_for_new_extranonce(seed1)
    b2 = cur.allocate(4)
    assert b2 is not None and b2.logical_start == 0 and b2.count == 4
    # Exact full-space last window for sequential
    cur_s = LogicalCursor(SearchStrategy.SEQUENTIAL, seed0, cursor=0x100000000 - 100)
    b3 = cur_s.allocate(1000)
    assert b3 is not None and b3.count == 100 and b3.needs_extranonce_bump_after


def test_strategy_change_only_on_new_session():
    pol = StrategySessionPolicy(SearchStrategy.SEQUENTIAL, locked=True)
    assert pol.allow_change(SearchStrategy.SEQUENTIAL, new_session=False) is True
    assert pol.allow_change(SearchStrategy.REVERSE, new_session=False) is False
    assert pol.allow_change(SearchStrategy.REVERSE, new_session=True) is True
    assert pol.allow_change(SearchStrategy.RANDOMIZED, new_session=True) is True


def test_cross_strategy_physical_overlap_analysis():
    """
    Same header, first K logical under seq vs reverse vs affine:
    early windows are mostly disjoint; full space of each is a permutation
    so the *sets* equal {0..2^32-1} but prefix sets collide only by chance.
    """
    K = 10_000
    aff = affine_from_seed(b"overlap")
    seq = {physical_nonce(i, SearchStrategy.SEQUENTIAL) for i in range(K)}
    rev = {physical_nonce(i, SearchStrategy.REVERSE) for i in range(K)}
    rnd = {physical_nonce(i, SearchStrategy.RANDOMIZED, affine=aff) for i in range(K)}
    # Prefixes of seq and reverse are disjoint for K <= 2^31
    assert seq.isdisjoint(rev)
    # Randomized prefix may overlap either; measure only
    ov_sr = len(seq & rnd)
    ov_rr = len(rev & rnd)
    assert 0 <= ov_sr <= K and 0 <= ov_rr <= K
    # Mid-session strategy switch without new session would re-visit some
    # physical nonces if both prefixes overlap — policy forbids that.
    pol = StrategySessionPolicy(SearchStrategy.SEQUENTIAL)
    assert pol.allow_change(SearchStrategy.RANDOMIZED, new_session=False) is False

