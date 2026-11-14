"""Coinbase shareout address / 2% fee / corrupt tx tests."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.coinbase import (  # noqa: E402
    COIN,
    address_to_script_pubkey,
    block_subsidy,
    expected_miner_and_fee,
    parse_tx,
    verify_coinbase_payout,
)

# Bilinen genesis P2PKH adresi
ADDR_P2PKH = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"


def _varint(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "little")
    if n <= 0xFFFFFFFF:
        return b"\xfe" + n.to_bytes(4, "little")
    return b"\xff" + n.to_bytes(8, "little")


def _push_height(height: int) -> bytes:
    raw = height.to_bytes((height.bit_length() + 7) // 8 or 1, "little")
    return bytes([len(raw)]) + raw


def make_coinbase(
    height: int,
    outputs: list[tuple[int, bytes]],
    extra_script: bytes = b"",
) -> bytes:
    script_sig = _push_height(height) + extra_script
    tx = b""
    tx += struct.pack("<I", 1)  # version
    tx += _varint(1)  # 1 input
    tx += b"\x00" * 32 + b"\xff\xff\xff\xff"  # prevout
    tx += _varint(len(script_sig)) + script_sig
    tx += b"\xff\xff\xff\xff"  # sequence
    tx += _varint(len(outputs))
    for value, script in outputs:
        tx += struct.pack("<Q", value)
        tx += _varint(len(script)) + script
    tx += struct.pack("<I", 0)  # locktime
    return tx


def test_address_to_script_p2pkh():
    script = address_to_script_pubkey(ADDR_P2PKH)
    assert script.startswith(b"\x76\xa9\x14")
    assert script.endswith(b"\x88\xac")
    assert len(script) == 25


def test_valid_payout_with_2pct_fee():
    height = 800_000
    subsidy = block_subsidy(height)
    # Basit: sadece subsidy, fee yok (tx fee=0)
    payment_out = subsidy
    miner, fee = expected_miner_and_fee(payment_out)
    user_script = address_to_script_pubkey(ADDR_P2PKH)
    pool_script = b"\x00\x14" + b"\x11" * 20  # sahte P2WPKH
    opreturn = b"\x6a\x24\xaa\x21\xa9\xed" + b"\x00" * 32  # witness commitment benzeri
    tx = make_coinbase(
        height,
        [
            (miner, user_script),
            (fee, pool_script),
            (0, opreturn),
        ],
    )
    # parse roundtrip
    _, outs = parse_tx(tx)
    assert len(outs) == 3
    assert outs[2].is_op_return

    check = verify_coinbase_payout(tx, ADDR_P2PKH)
    assert check.ok
    assert check.stop_mining is False
    assert check.amount_independently_verified is True
    assert check.user_value == miner
    assert check.expected_pool_fee == fee


def test_wrong_recipient_stops():
    height = 800_000
    subsidy = block_subsidy(height)
    miner, fee = expected_miner_and_fee(subsidy)
    other = b"\x76\xa9\x14" + b"\x22" * 20 + b"\x88\xac"
    pool_script = b"\x00\x14" + b"\x11" * 20
    tx = make_coinbase(height, [(miner, other), (fee, pool_script)])
    check = verify_coinbase_payout(tx, ADDR_P2PKH)
    assert check.ok is False
    assert check.stop_mining is True
    assert "no payment" in check.message.lower() or "scriptPubKey" in check.message


def test_short_payout_stops():
    height = 800_000
    subsidy = block_subsidy(height)
    miner, fee = expected_miner_and_fee(subsidy)
    user_script = address_to_script_pubkey(ADDR_P2PKH)
    pool_script = b"\x00\x14" + b"\x11" * 20
    # Shortfall to user
    tx = make_coinbase(
        height,
        [(miner - 1000, user_script), (fee + 1000, pool_script)],
    )
    check = verify_coinbase_payout(tx, ADDR_P2PKH)
    assert check.ok is False
    assert check.stop_mining is True
    assert "pay" in check.message.lower() or "expected" in check.message.lower()


def test_corrupt_tx_stops():
    check = verify_coinbase_payout(b"\x00\x01\x02", ADDR_P2PKH)
    assert check.ok is False
    assert check.stop_mining is True
    assert "parse" in check.message.lower()


def test_pool_wallet_coinbase_allowed_when_not_required():
    """2Miners BCH SOLO: pool-wallet coinbase — no stop, warning."""
    height = 800_000
    subsidy = block_subsidy(height)
    other = b"\x76\xa9\x14" + b"\x22" * 20 + b"\x88\xac"
    tx = make_coinbase(height, [(subsidy, other)])
    check = verify_coinbase_payout(
        tx, ADDR_P2PKH, enforce_fee_split=False, require_user_payout=False
    )
    assert check.ok is True
    assert check.stop_mining is False
    assert "pool" in check.message.lower() or "warning" in check.message.lower()


def test_amount_unverified_without_bip34():
    user_script = address_to_script_pubkey(ADDR_P2PKH)
    # scriptSig not BIP34 (no height push — empty script)
    tx = b""
    tx += struct.pack("<I", 1)
    tx += _varint(1)
    tx += b"\x00" * 32 + b"\xff\xff\xff\xff"
    tx += _varint(0)  # empty scriptSig → height None
    tx += b"\xff\xff\xff\xff"
    tx += _varint(1)
    tx += struct.pack("<Q", 50 * COIN) + _varint(len(user_script)) + user_script
    tx += struct.pack("<I", 0)
    check = verify_coinbase_payout(tx, ADDR_P2PKH)
    assert check.ok is True
    assert check.amount_independently_verified is False
    assert "not independently verified" in check.message
