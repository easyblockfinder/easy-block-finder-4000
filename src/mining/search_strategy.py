"""
Experimental Mining Search Strategy (offline PoC helpers).

Maps a logical cursor i ∈ [0, 2^32) onto a physical nonce via a bijection.
Does NOT claim higher block-finding probability — order only.

Production MiningJob / sha256d.cl are intentionally untouched by this module.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional


MASK32 = 0xFFFFFFFF
SPACE = 0x100000000


class SearchStrategy(str, Enum):
    SEQUENTIAL = "sequential"
    REVERSE = "reverse"
    RANDOMIZED = "randomized"


def seed_material(
    *,
    work_family_id: str,
    extranonce2_hex: str,
    strategy: SearchStrategy,
    session_salt: str = "",
) -> bytes:
    parts = [
        (work_family_id or "").strip().lower(),
        (extranonce2_hex or "").strip().lower(),
        strategy.value,
        (session_salt or "").strip(),
    ]
    return ("\n".join(parts)).encode("utf-8")


def seed_fingerprint(seed: bytes) -> str:
    return hashlib.sha256(seed).hexdigest()[:16]


@dataclass(frozen=True)
class AffineParams:
    """nonce = (a * logical + b) mod 2^32 with a odd ⇒ bijection on Z/2^32Z."""

    a: int
    b: int

    def __post_init__(self) -> None:
        a = int(self.a) & MASK32
        b = int(self.b) & MASK32
        if a != int(self.a) or b != int(self.b):
            object.__setattr__(self, "a", a)
            object.__setattr__(self, "b", b)
        if a & 1 == 0:
            raise ValueError("AffineParams.a must be odd (32-bit) for bijection")
        if not (0 <= a <= MASK32 and 0 <= b <= MASK32):
            raise ValueError("AffineParams a/b must be uint32")

    def map(self, logical: int) -> int:
        return (int(self.a) * (int(logical) & MASK32) + int(self.b)) & MASK32


def affine_from_seed(seed: bytes) -> AffineParams:
    digest = hashlib.sha256(seed).digest()
    a = int.from_bytes(digest[0:4], "little") | 1  # force odd → gcd(a,2^32)=1
    b = int.from_bytes(digest[4:8], "little") & MASK32
    return AffineParams(a=a & MASK32, b=b)


def is_bijective_strategy(strategy: SearchStrategy, affine: Optional[AffineParams] = None) -> bool:
    """
    Mathematical bijection on the full 32-bit domain:
      sequential: identity
      reverse:     involution i ↦ (2^32-1)-i
      randomized:  affine i ↦ a*i+b (mod 2^32) with a odd
    """
    if strategy is SearchStrategy.SEQUENTIAL:
        return True
    if strategy is SearchStrategy.REVERSE:
        return True
    if strategy is SearchStrategy.RANDOMIZED:
        return affine is not None and (int(affine.a) & 1) == 1 and 0 <= int(affine.a) <= MASK32
    return False


@dataclass(frozen=True)
class StrategySessionPolicy:
    """
    Design rule (not wired to live mining yet):
    Search strategy may only be selected at mining-session start.
    Mid-session changes are rejected to avoid mixed physical coverage
    under the same header/extranonce2 without a clear uniqueness ledger key.
    """

    strategy: SearchStrategy
    locked: bool = True

    def allow_change(self, new_strategy: SearchStrategy, *, new_session: bool) -> bool:
        if not self.locked:
            return True
        if new_strategy == self.strategy:
            return True
        return bool(new_session)


def physical_nonce(
    logical: int,
    strategy: SearchStrategy,
    *,
    affine: Optional[AffineParams] = None,
) -> int:
    i = int(logical) & MASK32
    if strategy is SearchStrategy.SEQUENTIAL:
        return i
    if strategy is SearchStrategy.REVERSE:
        return (MASK32 - i) & MASK32
    if strategy is SearchStrategy.RANDOMIZED:
        if affine is None:
            raise ValueError("randomized requires AffineParams")
        return affine.map(i)
    raise ValueError(f"unknown strategy: {strategy}")


def batch_nonce_base(
    logical_start: int,
    strategy: SearchStrategy,
) -> int:
    """
    GPU nonce_base for strategy kernel:
      sequential: nonce = base + tid
      reverse:    nonce = base - tid   (base = 0xFFFFFFFF - logical_start)
      randomized: logical index base (affine applied in-kernel)
    """
    ls = int(logical_start) & MASK32
    if strategy is SearchStrategy.SEQUENTIAL:
        return ls
    if strategy is SearchStrategy.REVERSE:
        return (MASK32 - ls) & MASK32
    if strategy is SearchStrategy.RANDOMIZED:
        return ls
    raise ValueError(f"unknown strategy: {strategy}")


@dataclass
class LogicalBatch:
    logical_start: int
    count: int
    nonce_base: int
    strategy: SearchStrategy
    affine: Optional[AffineParams]
    seed_fp: str
    needs_extranonce_bump_after: bool

    def physical_nonces(self) -> list[int]:
        return [
            physical_nonce(
                self.logical_start + k,
                self.strategy,
                affine=self.affine,
            )
            for k in range(self.count)
        ]


@dataclass
class LogicalCursor:
    """
    Host-side allocator mirroring MiningJob.allocate_batch semantics on a
    logical [0, 2^32) cursor. Wrap ⇒ caller should bump extranonce2 / refresh seed.
    """

    strategy: SearchStrategy
    seed: bytes
    cursor: int = 0
    _needs_bump: bool = False

    def __post_init__(self) -> None:
        self.affine = (
            affine_from_seed(self.seed)
            if self.strategy is SearchStrategy.RANDOMIZED
            else None
        )
        self.seed_fp = seed_fingerprint(self.seed)

    def allocate(self, count: int) -> Optional[LogicalBatch]:
        if self._needs_bump:
            return None  # caller must bump en2 + reset_for_new_extranonce
        start = int(self.cursor) & MASK32
        space = SPACE - start
        if space <= 0:
            self._needs_bump = True
            return None
        take = min(int(count), space)
        if take <= 0:
            return None
        base = batch_nonce_base(start, self.strategy)
        nxt = start + take
        bump_after = False
        if nxt >= SPACE:
            self.cursor = 0
            self._needs_bump = True
            bump_after = True
        else:
            self.cursor = nxt
        return LogicalBatch(
            logical_start=start,
            count=take,
            nonce_base=base,
            strategy=self.strategy,
            affine=self.affine,
            seed_fp=self.seed_fp,
            needs_extranonce_bump_after=bump_after,
        )

    def reset_for_new_extranonce(self, new_seed: bytes) -> None:
        self.seed = new_seed
        self.cursor = 0
        self._needs_bump = False
        self.__post_init__()

    @property
    def needs_extranonce_bump(self) -> bool:
        return bool(self._needs_bump)


def assert_affine_bijective_sample(affine: AffineParams, sample: int = 1 << 20) -> None:
    """Injectivity check on [0, sample). Full 2^32 is proven by a odd."""
    if affine.a & 1 == 0:
        raise AssertionError("a must be odd")
    seen: set[int] = set()
    for i in range(sample):
        n = affine.map(i)
        if n in seen:
            raise AssertionError(f"collision at logical={i} nonce={n}")
        seen.add(n)
    if len(seen) != sample:
        raise AssertionError("sample size mismatch")
