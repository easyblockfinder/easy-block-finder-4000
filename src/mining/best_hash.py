from __future__ import annotations

from mining.bitcoin import DIFF1_TARGET, bits_to_target

SUPPORTED_BEST_HASH_NETWORKS = frozenset({"btc", "bch"})


def hash_be_hex_to_int(hash_be_hex: str) -> int:
    s = hash_be_hex.strip().lower()
    if len(s) != 64:
        raise ValueError("hash_be_hex must be 64 hex chars")
    return int(s, 16)


def hash_digest_be_to_int(digest_be: bytes) -> int:
    if len(digest_be) != 32:
        raise ValueError("digest must be 32 bytes")
    return int.from_bytes(digest_be, "big")


def difficulty_from_hash_int(hash_int: int) -> float:
    if hash_int <= 0:
        raise ValueError("hash_int must be positive")
    return float(DIFF1_TARGET / hash_int)


def network_difficulty_from_nbits(nbits_hex: str) -> float:
    target = bits_to_target(nbits_hex)
    if target <= 0:
        raise ValueError("invalid nbits target")
    return float(DIFF1_TARGET / target)


def is_better_hash(candidate_int: int, record_int: int | None) -> bool:
    if candidate_int <= 0:
        return False
    if record_int is None:
        return True
    return candidate_int < record_int

def pick_best_candidate_hex(candidates: list[str]) -> str | None:
    """Return the smallest valid 64-hex (explorer-order) hash, or None."""
    best_hex: str | None = None
    best_int: int | None = None
    for raw in candidates:
        if not raw:
            continue
        try:
            value = hash_be_hex_to_int(raw)
        except (ValueError, AttributeError):
            continue
        if is_better_hash(value, best_int):
            best_int = value
            best_hex = raw.strip().lower()
    return best_hex
