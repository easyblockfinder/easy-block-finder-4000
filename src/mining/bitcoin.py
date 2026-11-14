"""Bitcoin SHA-256d, address, Merkle, and block header helpers."""

from __future__ import annotations

import hashlib
import math
import struct
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Iterable, Union

import base58
from bech32 import bech32_decode, convertbits

# Bitcoin main network target (difficulty 1): 0x00000000FFFF0000...
DIFF1_TARGET = int(
    "00000000FFFF0000000000000000000000000000000000000000000000000000",
    16,
)

DifficultyLike = Union[int, float, str, Decimal]


def hash256(data: bytes) -> bytes:
    """SHA-256d: SHA256(SHA256(data))."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def validate_bitcoin_address(address: str) -> tuple[bool, str]:
    """Verify Bitcoin mainnet recipient address. No default address; empty is rejected."""
    addr = (address or "").strip()
    if not addr:
        return False, "Bitcoin payout address required."

    if addr.startswith(("1", "3")):
        try:
            decoded = base58.b58decode_check(addr)
        except ValueError:
            return False, "Invalid Base58Check address."
        if len(decoded) != 21:
            return False, "Invalid address length."
        version = decoded[0]
        if version not in (0x00, 0x05):
            return False, "Only Bitcoin mainnet addresses are accepted."
        return True, ""

    if addr.lower().startswith("bc1"):
        hrp, data = bech32_decode(addr)
        if hrp != "bc" or data is None or len(data) < 1:
            return False, "Invalid bech32 (bc1) address."
        witver = data[0]
        witprog = convertbits(data[1:], 5, 8, False)
        if witprog is None:
            return False, "Invalid bech32 program."
        if witver == 0 and len(witprog) not in (20, 32):
            return False, "Invalid witness program length."
        if witver == 1 and len(witprog) != 32:
            return False, "Invalid Taproot (P2TR) program."
        if witver > 1:
            return False, "Unsupported witness version."
        return True, ""

    return False, "Unsupported address format (1… / 3… / bc1…)."


def validate_bch_address(address: str) -> tuple[bool, str]:
    """BCH mainnet: CashAddr (bitcoincash:q/p…) veya legacy 1…/3…."""
    addr = (address or "").strip()
    if not addr:
        return False, "BCH payout address required."
    lower = addr.lower()
    if lower.startswith("bitcoincash:") or (
        ":" not in addr and addr[:1].lower() in ("q", "p") and len(addr) >= 42
    ):
        try:
            from .cashaddr import decode_cashaddr

            decode_cashaddr(
                addr if ":" in addr else f"bitcoincash:{addr.lower()}"
            )
            return True, ""
        except ValueError as exc:
            return False, f"Invalid CashAddr: {exc}"
    if addr.startswith(("1", "3")):
        # Legacy BCH (same Base58 version bytes as BTC)
        return validate_bitcoin_address(addr)
    return False, "BCH address must be CashAddr (bitcoincash:q…/p…) or legacy 1…/3…."


def validate_xmr_address(address: str) -> tuple[bool, str]:
    """Monero mainnet adres: bloklu Base58 + Keccak-256 checksum.

    Netbyte: 0x12 standard, 0x2a subaddress, 0x13 integrated.
    Kryptex SOLO: standard/subaddress; integrated reddedilir.
    """
    from mining.keccak256 import keccak_256
    from mining.monero_base58 import decode as xmr_b58decode

    addr = (address or "").strip()
    if not addr:
        return False, "XMR payout address required."
    if len(addr) not in (95, 106):
        return False, "Invalid XMR address length (expected 95 or 106)."
    alphabet = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
    if any(c not in alphabet for c in addr):
        return False, "XMR address contains invalid base58 characters."
    try:
        raw = xmr_b58decode(addr)
    except ValueError as exc:
        return False, f"XMR Base58 decode failed: {exc}"
    if len(raw) < 69:
        return False, "XMR address decode too short."
    body, checksum = raw[:-4], raw[-4:]
    # Monero: Keccak-256 (not SHA3-256)
    digest = keccak_256(body)[:4]
    if digest != checksum:
        return False, "XMR address checksum invalid (Keccak-256)."
    netbyte = body[0]
    # mainnet
    if netbyte == 0x12:
        if len(body) != 65:
            return False, "XMR standard address body length invalid."
        return True, ""
    if netbyte == 0x2A:
        if len(body) != 65:
            return False, "XMR subaddress body length invalid."
        return True, ""
    if netbyte == 0x13:
        return (
            False,
            "Integrated XMR addresses are not supported on Kryptex SOLO; "
            "use standard (4…) or subaddress (8…).",
        )
    if netbyte in (0x35, 0x3F, 0x36, 0x18, 0x24, 0x19):
        return False, "Only Monero mainnet addresses are accepted (not testnet/stagenet)."
    return False, f"Bilinmeyen XMR netbyte 0x{netbyte:02x}."


def validate_rvn_address(address: str) -> tuple[bool, str]:
    """Ravencoin mainnet (R… Base58Check)."""
    addr = (address or "").strip()
    if not addr:
        return False, "RVN payout address required."
    if not addr.startswith("R"):
        return False, "RVN address must start with R…."
    try:
        decoded = base58.b58decode_check(addr)
    except ValueError:
        return False, "Invalid RVN Base58Check address."
    if len(decoded) != 21:
        return False, "Invalid RVN address length."
    if decoded[0] != 0x3C:
        return False, "Only Ravencoin mainnet (version 0x3C) is accepted."
    return True, ""


def validate_erg_address(address: str) -> tuple[bool, str]:
    """Ergo mainnet P2PK (9…); blake2b256 checksum."""
    addr = (address or "").strip()
    if not addr:
        return False, "ERG payout address required."
    if not addr.startswith("9"):
        return False, "ERG mainnet P2PK address must start with 9…."
    try:
        raw = base58.b58decode(addr)
    except ValueError:
        return False, "Invalid ERG Base58 address."
    if len(raw) < 5:
        return False, "ERG address too short."
    body, checksum = raw[:-4], raw[-4:]
    digest = hashlib.blake2b(body, digest_size=32).digest()[:4]
    if digest != checksum:
        return False, "ERG address checksum invalid."
    if body[0] != 0x01:
        return False, "Only Ergo mainnet P2PK (prefix 0x01) is accepted."
    return True, ""


def validate_address_for_network(network_id: str, address: str) -> tuple[bool, str]:
    nid = (network_id or "btc").strip().lower()
    if nid == "bch":
        return validate_bch_address(address)
    if nid == "btc":
        return validate_bitcoin_address(address)
    if nid == "xmr":
        return validate_xmr_address(address)
    if nid == "rvn":
        return validate_rvn_address(address)
    if nid == "erg":
        return validate_erg_address(address)
    return False, f"Address validation is not available for this network: {nid}"


def bits_to_target(nbits_hex: str) -> int:
    """Compact nBits → 256-bit hedef (int)."""
    nbits = int(nbits_hex, 16)
    exponent = nbits >> 24
    mantissa = nbits & 0xFFFFFF
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa << (8 * (exponent - 3))


def share_target_from_difficulty(difficulty: DifficultyLike) -> int:
    """Stratum pool difficulty → share target (integer ratio; int(difficulty) doesn't cut it)."""
    if isinstance(difficulty, bool):
        raise ValueError("Invalid difficulty.")
    if isinstance(difficulty, float) and (
        math.isnan(difficulty) or math.isinf(difficulty)
    ):
        raise ValueError("Zorluk NaN/Inf olamaz.")
    try:
        # float → str → Decimal → Fraction (Default Decimal prec is not sufficient for DIFF1)
        if isinstance(difficulty, Decimal):
            d = difficulty
        elif isinstance(difficulty, float):
            d = Decimal(str(difficulty))
        else:
            d = Decimal(difficulty)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Difficulty must be numeric.") from exc
    if not d.is_finite():
        raise ValueError("Zorluk NaN/Inf olamaz.")
    if d <= 0:
        raise ValueError("Difficulty must be positive.")
    frac = Fraction(d)
    return (DIFF1_TARGET * frac.denominator) // frac.numerator


def is_hash_below_target(block_hash_le: bytes, target: int) -> bool:
    """
    block_hash_le: little-endian raw bytes of SHA-256d result (32 bytes).
    Bitcoin compare: hash as integer (big-endian view) <= target.
    """
    hash_int = int.from_bytes(block_hash_le[::-1], "big")
    return hash_int <= target


def extranonce2_bytes(value: int, size: int) -> bytes:
    return value.to_bytes(size, "big")


def build_coinbase(coinb1_hex: str, extranonce1_hex: str, extranonce2: bytes, coinb2_hex: str) -> bytes:
    return bytes.fromhex(coinb1_hex) + bytes.fromhex(extranonce1_hex) + extranonce2 + bytes.fromhex(coinb2_hex)


def build_merkle_root(coinbase: bytes, merkle_branches_hex: Iterable[str]) -> bytes:
    """Coinbase hash + stratum Merkle branches → Merkle root (internal LE byte order)."""
    current = hash256(coinbase)
    for branch_hex in merkle_branches_hex:
        branch = bytes.fromhex(branch_hex)
        current = hash256(current + branch)
    return current


def _uint32_le_hex_to_bytes(hex32: str) -> bytes:
    """Convert the 32-byte hex field of Stratum's 4-byte groups, which is reversed, to bytes."""
    raw = bytes.fromhex(hex32)
    if len(raw) != 32:
        raise ValueError("32 bayt bekleniyor.")
    # Stratum: Every 4 bytes come as a little-endian word; used as in the header.
    return b"".join(raw[i : i + 4][::-1] for i in range(0, 32, 4))


def stratum_prevhash_to_header_bytes(prevhash_hex: str) -> bytes:
    return _uint32_le_hex_to_bytes(prevhash_hex)


def merkle_root_to_header_bytes(merkle_root: bytes) -> bytes:
    """
    Coinbase+merkle_branch hash256 output -> header merkle field.

    Bitcoin header merkle root uses double-SHA256 raw (internal) byte order.
    No per-32-bit word swap like prevhash.
    """
    if len(merkle_root) != 32:
        raise ValueError("Merkle root must be 32 bytes.")
    return merkle_root


def build_block_header(
    version_hex: str,
    prevhash_hex: str,
    merkle_root: bytes,
    ntime_hex: str,
    nbits_hex: str,
    nonce: int,
) -> bytes:
    """Create an 80-byte block header (Stratum/Bitcoin serialization)."""
    version = struct.pack("<I", int(version_hex, 16))
    prev = stratum_prevhash_to_header_bytes(prevhash_hex)
    merkle = merkle_root_to_header_bytes(merkle_root)
    ntime = struct.pack("<I", int(ntime_hex, 16))
    nbits = struct.pack("<I", int(nbits_hex, 16))
    nonce_b = struct.pack("<I", nonce & 0xFFFFFFFF)
    header = version + prev + merkle + ntime + nbits + nonce_b
    if len(header) != 80:
        raise RuntimeError(f"Invalid header length: {len(header)}")
    return header


def nonce_to_submit_hex(nonce: int) -> str:
    """
    GPU/CPU uint32 nonce → mining.submit nonce hex.

    Stratum: nonce as big-endian hex; pool reads int(hex,16) and writes LE into header.
    Same integer the GPU scanned (not a byte reversal).
    """
    return f"{nonce & 0xFFFFFFFF:08x}"


def nonce_from_submit_hex(nonce_hex: str) -> int:
    return int(nonce_hex, 16) & 0xFFFFFFFF


def rebuild_header_from_submit(
    *,
    version_hex: str,
    prevhash_hex: str,
    coinb1_hex: str,
    coinb2_hex: str,
    merkle_branches: Iterable[str],
    extranonce1_hex: str,
    extranonce2_hex: str,
    ntime_hex: str,
    nbits_hex: str,
    nonce_hex: str,
) -> dict:
    """
    Rebuild 80-byte header from fields independent of mining.submit.
    Does not re-hash the GPU buffer; follows coinbase -> merkle -> serialize path.
    """
    en2 = bytes.fromhex(extranonce2_hex)
    coinbase = build_coinbase(coinb1_hex, extranonce1_hex, en2, coinb2_hex)
    merkle = build_merkle_root(coinbase, merkle_branches)
    nonce = nonce_from_submit_hex(nonce_hex)
    header = build_block_header(
        version_hex, prevhash_hex, merkle, ntime_hex, nbits_hex, nonce
    )
    digest = header_hash(header)
    return {
        "coinbase": coinbase,
        "merkle_root": merkle,
        "header": header,
        "nonce": nonce,
        "nonce_submit_hex": nonce_to_submit_hex(nonce),
        "hash_le": digest,
        "hash_be_hex": digest[::-1].hex(),
        "hash_le_hex": digest.hex(),
    }


def header_hash(header: bytes) -> bytes:
    """80-byte header → SHA-256d (little-endian raw output)."""
    if len(header) != 80:
        raise ValueError("Header must be 80 bytes.")
    return hash256(header)


def midstate_from_header(header: bytes) -> bytes:
    """SHA-256 midstate of the first 64 bytes (8x uint32 little-endian)."""
    if len(header) < 64:
        raise ValueError("At least 64 bytes required for midstate.")
    h = hashlib.sha256()
    h.update(header[:64])
    # No direct access to hashlib midstate; manual SHA-256 compress is required.
    return _sha256_midstate(header[:64])


# SHA-256 sabitleri
_K = (
    0x428A2F98,
    0x71374491,
    0xB5C0FBCF,
    0xE9B5DBA5,
    0x3956C25B,
    0x59F111F1,
    0x923F82A4,
    0xAB1C5ED5,
    0xD807AA98,
    0x12835B01,
    0x243185BE,
    0x550C7DC3,
    0x72BE5D74,
    0x80DEB1FE,
    0x9BDC06A7,
    0xC19BF174,
    0xE49B69C1,
    0xEFBE4786,
    0x0FC19DC6,
    0x240CA1CC,
    0x2DE92C6F,
    0x4A7484AA,
    0x5CB0A9DC,
    0x76F988DA,
    0x983E5152,
    0xA831C66D,
    0xB00327C8,
    0xBF597FC7,
    0xC6E00BF3,
    0xD5A79147,
    0x06CA6351,
    0x14292967,
    0x27B70A85,
    0x2E1B2138,
    0x4D2C6DFC,
    0x53380D13,
    0x650A7354,
    0x766A0ABB,
    0x81C2C92E,
    0x92722C85,
    0xA2BFE8A1,
    0xA81A664B,
    0xC24B8B70,
    0xC76C51A3,
    0xD192E819,
    0xD6990624,
    0xF40E3585,
    0x106AA070,
    0x19A4C116,
    0x1E376C08,
    0x2748774C,
    0x34B0BCB5,
    0x391C0CB3,
    0x4ED8AA4A,
    0x5B9CCA4F,
    0x682E6FF3,
    0x748F82EE,
    0x78A5636F,
    0x84C87814,
    0x8CC70208,
    0x90BEFFFA,
    0xA4506CEB,
    0xBEF9A3F7,
    0xC67178F2,
)

_IV = (
    0x6A09E667,
    0xBB67AE85,
    0x3C6EF372,
    0xA54FF53A,
    0x510E527F,
    0x9B05688C,
    0x1F83D9AB,
    0x5BE0CD19,
)


def _rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF


def _sha256_compress(state: list[int], block: bytes) -> list[int]:
    w = list(struct.unpack(">16I", block))
    for i in range(16, 64):
        s0 = _rotr(w[i - 15], 7) ^ _rotr(w[i - 15], 18) ^ (w[i - 15] >> 3)
        s1 = _rotr(w[i - 2], 17) ^ _rotr(w[i - 2], 19) ^ (w[i - 2] >> 10)
        w.append((w[i - 16] + s0 + w[i - 7] + s1) & 0xFFFFFFFF)

    a, b, c, d, e, f, g, h = state
    for i in range(64):
        s1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
        ch = (e & f) ^ ((~e) & g)
        t1 = (h + s1 + ch + _K[i] + w[i]) & 0xFFFFFFFF
        s0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
        maj = (a & b) ^ (a & c) ^ (b & c)
        t2 = (s0 + maj) & 0xFFFFFFFF
        h = g
        g = f
        f = e
        e = (d + t1) & 0xFFFFFFFF
        d = c
        c = b
        b = a
        a = (t1 + t2) & 0xFFFFFFFF

    return [
        (state[0] + a) & 0xFFFFFFFF,
        (state[1] + b) & 0xFFFFFFFF,
        (state[2] + c) & 0xFFFFFFFF,
        (state[3] + d) & 0xFFFFFFFF,
        (state[4] + e) & 0xFFFFFFFF,
        (state[5] + f) & 0xFFFFFFFF,
        (state[6] + g) & 0xFFFFFFFF,
        (state[7] + h) & 0xFFFFFFFF,
    ]


def _sha256_midstate(block64: bytes) -> bytes:
    """Midstate after a single 64-byte block (little-endian uint32 x8)."""
    state = _sha256_compress(list(_IV), block64)
    return struct.pack("<8I", *state)


def sha256_midstate_words(block64: bytes) -> tuple[int, ...]:
    state = _sha256_compress(list(_IV), block64)
    return tuple(state)


def verify_header_against_targets(
    header: bytes,
    share_target: int,
    network_target: int,
) -> dict:
    """Independent verification with the CPU. It evaluates the share and network target separately."""
    digest = header_hash(header)
    hash_int = int.from_bytes(digest[::-1], "big")
    return {
        "hash_le": digest,
        "hash_be_hex": digest[::-1].hex(),
        "meets_share": hash_int <= share_target,
        "meets_network": hash_int <= network_target,
        "hash_int": hash_int,
    }
