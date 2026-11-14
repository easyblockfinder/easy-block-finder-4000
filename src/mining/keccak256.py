"""Keccak-256 (not NIST SHA3-256) — used for Monero checksum.

Expected digest for empty input:
c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470
"""

from __future__ import annotations


def keccak_256(data: bytes) -> bytes:
    try:
        from Crypto.Hash import keccak as _keccak
    except ImportError:  # pragma: no cover
        from Cryptodome.Hash import keccak as _keccak  # type: ignore

    h = _keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()
