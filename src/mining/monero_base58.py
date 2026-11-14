"""Monero block-encoded Base58 (not Bitcoin Base58Check).

Kaynak: monero-ecosystem/monero-python monero/base58.py (BSD-3-Clause).
"""

from __future__ import annotations

_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58BASE = 58
_UINT64MAX = 2**64
_ENCODED_BLOCK_SIZES = [0, 2, 3, 5, 6, 7, 9, 10, 11]
_FULL_BLOCK_SIZE = 8
_FULL_ENCODED_BLOCK_SIZE = 11


def _uint8be_to_64(data: bytes | bytearray) -> int:
    if not (1 <= len(data) <= 8):
        raise ValueError(f"Invalid input length: {len(data)}")
    res = 0
    for b in data:
        res = (res << 8) | int(b)
    return res


def _uint64_to_8be(num: int, size: int) -> bytearray:
    if size < 1 or size > 8:
        raise ValueError(f"Invalid size: {size}")
    res = bytearray(size)
    for i in range(size - 1, -1, -1):
        res[i] = num % 256
        num //= 256
    return res


def _decode_block(data: bytearray, buf: bytearray, index: int) -> None:
    l_data = len(data)
    if l_data < 1 or l_data > _FULL_ENCODED_BLOCK_SIZE:
        raise ValueError(f"Invalid block length: {l_data}")
    try:
        res_size = _ENCODED_BLOCK_SIZES.index(l_data)
    except ValueError as exc:
        raise ValueError(f"Invalid block size: {l_data}") from exc
    if res_size <= 0:
        raise ValueError(f"Invalid block size: {res_size}")

    res_num = 0
    order = 1
    for i in range(l_data - 1, -1, -1):
        try:
            digit = _ALPHABET.index(data[i])
        except ValueError as exc:
            raise ValueError(f"Invalid symbol: {chr(data[i])}") from exc
        product = order * digit + res_num
        if product > _UINT64MAX:
            raise ValueError("Overflow in base58 block")
        res_num = product
        order *= _B58BASE

    if res_size < _FULL_BLOCK_SIZE and (2 ** (8 * res_size)) <= res_num:
        raise ValueError("Overflow: value doesn't fit block")

    tmp = _uint64_to_8be(res_num, res_size)
    buf[index : index + len(tmp)] = tmp


def decode(enc: str) -> bytes:
    """Monero Base58 string → ham baytlar."""
    if not enc:
        return b""
    data_in = bytearray(enc, encoding="ascii")
    l_enc = len(data_in)
    full_block_count = l_enc // _FULL_ENCODED_BLOCK_SIZE
    last_block_size = l_enc % _FULL_ENCODED_BLOCK_SIZE
    try:
        last_decoded = _ENCODED_BLOCK_SIZES.index(last_block_size)
    except ValueError as exc:
        raise ValueError(f"Invalid encoded length: {l_enc}") from exc

    data_size = full_block_count * _FULL_BLOCK_SIZE + last_decoded
    out = bytearray(data_size)
    for i in range(full_block_count):
        start = i * _FULL_ENCODED_BLOCK_SIZE
        _decode_block(
            data_in[start : start + _FULL_ENCODED_BLOCK_SIZE],
            out,
            i * _FULL_BLOCK_SIZE,
        )
    if last_block_size > 0:
        start = full_block_count * _FULL_ENCODED_BLOCK_SIZE
        _decode_block(
            data_in[start : start + last_block_size],
            out,
            full_block_count * _FULL_BLOCK_SIZE,
        )
    return bytes(out)
