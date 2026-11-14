"""Coinbase transaction parsing and reward address / share verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import base58
from bech32 import bech32_decode, convertbits

from .bitcoin import build_coinbase, hash256

COIN = 100_000_000
# CKPool solo: 2% service fee based on the block reward (subsidy+fee total output).
POOL_FEE_NUM = 2
POOL_FEE_DEN = 100


@dataclass(frozen=True)
class TxOutput:
    value: int
    script: bytes

    @property
    def is_op_return(self) -> bool:
        return len(self.script) >= 1 and self.script[0] == 0x6A

    @property
    def is_payment(self) -> bool:
        return self.value > 0 and not self.is_op_return


@dataclass(frozen=True)
class PayoutCheck:
    ok: bool
    stop_mining: bool
    message: str
    height: Optional[int] = None
    subsidy: Optional[int] = None
    total_out: int = 0
    payment_out: int = 0
    user_value: int = 0
    expected_user: Optional[int] = None
    expected_pool_fee: Optional[int] = None
    amount_independently_verified: bool = False
    user_script_hex: str = ""


def address_to_script_pubkey(address: str) -> bytes:
    """Recipient address → scriptPubKey (raw bytes). The address text is not searched for in the tx."""
    addr = (address or "").strip()
    if not addr:
        raise ValueError("Address is empty.")

    lower = addr.lower()
    if lower.startswith("bitcoincash:") or (
        ":" not in addr and addr[:1].lower() in ("q", "p") and len(addr) >= 42
    ):
        from .cashaddr import cashaddr_to_script_pubkey

        return cashaddr_to_script_pubkey(
            addr if ":" in addr else f"bitcoincash:{addr.lower()}"
        )

    if addr.startswith(("1", "3")):
        decoded = base58.b58decode_check(addr)
        if len(decoded) != 21:
            raise ValueError("Invalid Base58 address length.")
        version, payload = decoded[0], decoded[1:]
        if version == 0x00:
            return b"\x76\xa9\x14" + payload + b"\x88\xac"  # P2PKH
        if version == 0x05:
            return b"\xa9\x14" + payload + b"\x87"  # P2SH
        raise ValueError("Unsupported Base58 version.")

    if addr.lower().startswith("bc1"):
        hrp, data = bech32_decode(addr)
        if hrp != "bc" or data is None:
            raise ValueError("Invalid bech32.")
        witver = data[0]
        witprog = convertbits(data[1:], 5, 8, False)
        if witprog is None:
            raise ValueError("Invalid witness program.")
        prog = bytes(witprog)
        if witver == 0 and len(prog) == 20:
            return b"\x00\x14" + prog  # P2WPKH
        if witver == 0 and len(prog) == 32:
            return b"\x00\x20" + prog  # P2WSH
        if witver == 1 and len(prog) == 32:
            return b"\x51\x20" + prog  # P2TR
        raise ValueError("Unsupported witness program.")

    raise ValueError("Unsupported address format.")


def _read_varint(data: bytes, i: int) -> tuple[int, int]:
    if i >= len(data):
        raise ValueError("Varint overflow.")
    first = data[i]
    i += 1
    if first < 0xFD:
        return first, i
    if first == 0xFD:
        return int.from_bytes(data[i : i + 2], "little"), i + 2
    if first == 0xFE:
        return int.from_bytes(data[i : i + 4], "little"), i + 4
    return int.from_bytes(data[i : i + 8], "little"), i + 8


def _read_bytes(data: bytes, i: int, n: int) -> tuple[bytes, int]:
    j = i + n
    if j > len(data):
        raise ValueError("Tx byte overflow.")
    return data[i:j], j


def parse_tx(raw: bytes) -> tuple[list[dict], list[TxOutput]]:
    """
    Parse legacy or marker=0000 segwit tx.
    Returns: (inputs meta, outputs). Witness data is not needed for payout checks.
    """
    if len(raw) < 10:
        raise ValueError("Tx too short.")
    i = 0
    _version, i = int.from_bytes(raw[i : i + 4], "little"), i + 4
    segwit = False
    if i + 2 <= len(raw) and raw[i] == 0x00 and raw[i + 1] != 0x00:
        # marker 0x00, flag != 0
        segwit = True
        i += 2

    nin, i = _read_varint(raw, i)
    inputs: list[dict] = []
    for _ in range(nin):
        prev, i = _read_bytes(raw, i, 36)
        script_len, i = _read_varint(raw, i)
        script, i = _read_bytes(raw, i, script_len)
        seq, i = _read_bytes(raw, i, 4)
        inputs.append({"prev": prev, "script": script, "sequence": seq})

    nout, i = _read_varint(raw, i)
    outputs: list[TxOutput] = []
    for _ in range(nout):
        value = int.from_bytes(raw[i : i + 8], "little")
        i += 8
        slen, i = _read_varint(raw, i)
        script, i = _read_bytes(raw, i, slen)
        outputs.append(TxOutput(value=value, script=script))

    if segwit:
        for _ in range(nin):
            nitems, i = _read_varint(raw, i)
            for _ in range(nitems):
                ilen, i = _read_varint(raw, i)
                _, i = _read_bytes(raw, i, ilen)

    if i + 4 > len(raw):
        raise ValueError("Locktime eksik.")
    return inputs, outputs


def bip34_height(script_sig: bytes) -> Optional[int]:
    """BIP34: scriptSig first push = block height (CScript num)."""
    if not script_sig:
        return None
    n = script_sig[0]
    if n == 0 or n > 8 or 1 + n > len(script_sig):
        return None
    raw = script_sig[1 : 1 + n]
    # little-endian signed minimal
    return int.from_bytes(raw, "little")


def block_subsidy(height: int) -> int:
    if height < 0:
        raise ValueError("Negative height.")
    era = height // 210_000
    if era >= 64:
        return 0
    return (50 * COIN) >> era


def expected_miner_and_fee(total_payment_out: int) -> tuple[int, int]:
    """
    Yuvarlama: pool_fee = floor(total * 2 / 100), miner = total - pool_fee.
    OP_RETURN (zero value) outputs do not affect the total.
    """
    if total_payment_out < 0:
        raise ValueError("Negatif toplam.")
    fee = (total_payment_out * POOL_FEE_NUM) // POOL_FEE_DEN
    miner = total_payment_out - fee
    return miner, fee


def verify_coinbase_payout(
    coinbase_tx: bytes,
    payout_address: str,
    *,
    pool_fee_num: int = POOL_FEE_NUM,
    pool_fee_den: int = POOL_FEE_DEN,
    enforce_fee_split: bool = True,
    require_user_payout: bool = True,
) -> PayoutCheck:
    try:
        user_script = address_to_script_pubkey(payout_address)
    except ValueError as exc:
        return PayoutCheck(
            ok=False,
            stop_mining=True,
            message=f"Could not build payout address scriptPubKey: {exc}",
        )

    try:
        inputs, outputs = parse_tx(coinbase_tx)
    except ValueError as exc:
        return PayoutCheck(
            ok=False,
            stop_mining=True,
            message=f"Could not parse coinbase transaction: {exc}",
            user_script_hex=user_script.hex(),
        )

    if not inputs:
        return PayoutCheck(
            ok=False,
            stop_mining=True,
            message="No coinbase input.",
            user_script_hex=user_script.hex(),
        )

    height = bip34_height(inputs[0]["script"])
    subsidy = block_subsidy(height) if height is not None else None

    total_out = sum(o.value for o in outputs)
    payment_out = sum(o.value for o in outputs if o.is_payment)
    user_value = sum(o.value for o in outputs if o.script == user_script and o.is_payment)

    if user_value <= 0:
        if require_user_payout:
            return PayoutCheck(
                ok=False,
                stop_mining=True,
                message=(
                    "No payment to user scriptPubKey in coinbase "
                    f"(script={user_script.hex()[:24]}…)."
                ),
                height=height,
                subsidy=subsidy,
                total_out=total_out,
                payment_out=payment_out,
                user_value=0,
                user_script_hex=user_script.hex(),
            )
        # 2Miners BCH SOLO, etc.: reward pool wallet → account payout
        return PayoutCheck(
            ok=True,
            stop_mining=False,
            message=(
                "WARNING: No user address in coinbase — reward goes to pool wallet "
                "(2Miners SOLO model). Mining continues; payout tied to pool account, "
                "on-chain address not verified instantly."
            ),
            height=height,
            subsidy=subsidy,
            total_out=total_out,
            payment_out=payment_out,
            user_value=0,
            user_script_hex=user_script.hex(),
        )

    fee = (payment_out * pool_fee_num) // pool_fee_den if pool_fee_den else 0
    expected_user = payment_out - fee
    expected_fee = fee

    # Independent amount: CKPool-style fee split only when enforce_fee_split=True
    amount_verified = False
    msg_extra = ""
    if enforce_fee_split and height is not None and subsidy is not None:
        if payment_out < subsidy:
            return PayoutCheck(
                ok=False,
                stop_mining=True,
                message=(
                    f"Payment outputs total ({payment_out}) below subsidy ({subsidy}); "
                    "corrupt or incomplete coinbase."
                ),
                height=height,
                subsidy=subsidy,
                total_out=total_out,
                payment_out=payment_out,
                user_value=user_value,
                expected_user=expected_user,
                expected_pool_fee=expected_fee,
                user_script_hex=user_script.hex(),
            )
        if user_value != expected_user:
            return PayoutCheck(
                ok=False,
                stop_mining=True,
                message=(
                    f"Incorrect share: user={user_value} satoshi, "
                    f"expected={expected_user} (total_payment={payment_out}, "
                    f"fee_num={pool_fee_num}/{pool_fee_den} pool={expected_fee}, "
                    f"height={height})."
                ),
                height=height,
                subsidy=subsidy,
                total_out=total_out,
                payment_out=payment_out,
                user_value=user_value,
                expected_user=expected_user,
                expected_pool_fee=expected_fee,
                user_script_hex=user_script.hex(),
            )
        amount_verified = True
        msg_extra = (
            f"Payout OK: {user_value} satoshi → scriptPubKey; "
            f"fee={expected_fee}; height={height} subsidy={subsidy}."
        )
    elif not enforce_fee_split:
        msg_extra = (
            f"User scriptPubKey payment present ({user_value} satoshi); "
            "pool fee/subsidy ratio not enforced (BCH/other SOLO)."
        )
    else:
        msg_extra = (
            f"User payout {user_value} satoshi output; "
            "amount not independently verified (no BIP34 height/subsidy)."
        )

    return PayoutCheck(
        ok=True,
        stop_mining=False,
        message=msg_extra,
        height=height,
        subsidy=subsidy,
        total_out=total_out,
        payment_out=payment_out,
        user_value=user_value,
        expected_user=expected_user if amount_verified else None,
        expected_pool_fee=expected_fee if amount_verified else None,
        amount_independently_verified=amount_verified,
        user_script_hex=user_script.hex(),
    )


def verify_job_coinbase_payout(
    *,
    coinb1: str,
    coinb2: str,
    extranonce1: str,
    extranonce2_hex: str,
    payout_address: str,
    pool_fee_num: int = POOL_FEE_NUM,
    pool_fee_den: int = POOL_FEE_DEN,
    enforce_fee_split: bool = True,
    require_user_payout: bool = True,
) -> PayoutCheck:
    en2 = bytes.fromhex(extranonce2_hex)
    tx = build_coinbase(coinb1, extranonce1, en2, coinb2)
    return verify_coinbase_payout(
        tx,
        payout_address,
        pool_fee_num=pool_fee_num,
        pool_fee_den=pool_fee_den,
        enforce_fee_split=enforce_fee_split,
        require_user_payout=require_user_payout,
    )


def coinbase_txid(coinbase_tx: bytes) -> str:
    """Legacy txid (hash256 of full raw as given for serialization, excluding witness)."""
    return hash256(coinbase_tx)[::-1].hex()
