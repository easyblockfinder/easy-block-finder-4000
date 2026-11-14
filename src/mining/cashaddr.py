"""Bitcoin Cash CashAddr decode (mainnet bitcoincash)."""

from __future__ import annotations

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_CHARSET_MAP = {c: i for i, c in enumerate(CHARSET)}


def _polymod(values: list[int]) -> int:
    c = 1
    for d in values:
        c0 = c >> 35
        c = ((c & 0x07FFFFFFFF) << 5) ^ d
        if c0 & 0x01:
            c ^= 0x98F2BC8E61
        if c0 & 0x02:
            c ^= 0x79B76D99E2
        if c0 & 0x04:
            c ^= 0xF33E5FB3C4
        if c0 & 0x08:
            c ^= 0xAE2EABE2A8
        if c0 & 0x10:
            c ^= 0x1E4F43E470
    return c ^ 1


def _prefix_expand(prefix: str) -> list[int]:
    return [ord(c) & 0x1F for c in prefix] + [0]


def _convertbits(data: list[int], from_bits: int, to_bits: int, pad: bool = True) -> list[int] | None:
    acc = 0
    bits = 0
    ret: list[int] = []
    maxv = (1 << to_bits) - 1
    for value in data:
        if value < 0 or value >> from_bits:
            return None
        acc = (acc << from_bits) | value
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (to_bits - bits)) & maxv)
    elif bits >= from_bits or ((acc << (to_bits - bits)) & maxv):
        return None
    return ret


def decode_cashaddr(address: str, *, expected_prefix: str = "bitcoincash") -> tuple[str, int, bytes]:
    """
    Returns: (prefix, version_byte, payload_hash).
    version_byte: 0=P2PKH20, 8=P2SH20, …
    """
    addr = (address or "").strip()
    if not addr:
        raise ValueError("CashAddr is empty.")
    lower = addr.lower()
    if ":" in lower:
        prefix, payload = lower.split(":", 1)
    else:
        prefix, payload = expected_prefix, lower
    if prefix != expected_prefix:
        raise ValueError(f"Beklenen prefix {expected_prefix}, gelen {prefix}.")
    if payload != payload.lower() and payload != payload.upper():
        raise ValueError("CashAddr mixed case.")
    payload = payload.lower()
    data: list[int] = []
    for ch in payload:
        if ch not in _CHARSET_MAP:
            raise ValueError("Invalid CashAddr character.")
        data.append(_CHARSET_MAP[ch])
    if len(data) < 8:
        raise ValueError("CashAddr is too short.")
    if _polymod(_prefix_expand(prefix) + data) != 0:
        raise ValueError("CashAddr checksum is incorrect.")
    decoded = _convertbits(data[:-8], 5, 8, False)
    if decoded is None or not decoded:
        raise ValueError("CashAddr payload could not be decoded.")
    version = decoded[0]
    body = bytes(decoded[1:])
    size_bits = version & 0x07
    size_map = {0: 20, 1: 24, 2: 28, 3: 32, 4: 40, 5: 48, 6: 56, 7: 64}
    expected_len = size_map.get(size_bits)
    if expected_len is None or len(body) != expected_len:
        raise ValueError("CashAddr hash length does not match.")
    return prefix, version, body


def cashaddr_to_script_pubkey(address: str) -> bytes:
    _prefix, version, body = decode_cashaddr(address)
    type_bits = (version >> 3) & 0x0F
    if type_bits == 0 and len(body) == 20:
        return b"\x76\xa9\x14" + body + b"\x88\xac"  # P2PKH
    if type_bits == 1 and len(body) == 20:
        return b"\xa9\x14" + body + b"\x87"  # P2SH20
    if type_bits == 1 and len(body) == 32:
        return b"\xaa\x20" + body + b"\x87"  # P2SH32 (OP_HASH256)
    raise ValueError("Unsupported CashAddr type.")
