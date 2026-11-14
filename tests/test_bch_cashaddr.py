"""BCH CashAddr andrification and scriptPubKey."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.bitcoin import (  # noqa: E402
    validate_address_for_network,
    validate_bch_address,
)
from mining.cashaddr import cashaddr_to_script_pubkey, decode_cashaddr  # noqa: E402
from mining.coinbase import address_to_script_pubkey  # noqa: E402
from networks.profiles import get_profile  # noqa: E402

# Dokumantasyon andctor: legacy genesis P2PKH ↔ CashAddr
CASH = "bitcoincash:qp3wjpa3tjlj042z2wv7hahsldgwhwy0rq9sywjpyy"
LEGACY = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"


def test_cashaddr_matches_legacy_hash160():
    _p, version, body = decode_cashaddr(CASH)
    assert version == 0
    import base58

    assert body == base58.b58decode_check(LEGACY)[1:]


def test_validate_bch_cashaddr_and_legacy():
    ok, err = validate_bch_address(CASH)
    assert ok, err
    ok, err = validate_bch_address(CASH.split(":", 1)[1])
    assert ok, err
    ok, err = validate_bch_address(LEGACY)
    assert ok, err
    ok, _ = validate_bch_address("bc1qinvalidforbch")
    assert not ok


def test_network_validator_routes():
    ok, _ = validate_address_for_network("bch", CASH)
    assert ok
    ok, _ = validate_address_for_network("btc", CASH)
    assert not ok


def test_script_pubkey_cashaddr_equals_legacy():
    assert address_to_script_pubkey(CASH) == address_to_script_pubkey(LEGACY)
    assert cashaddr_to_script_pubkey(CASH).hex().startswith("76a914")


def test_bch_profile_ready():
    p = get_profile("bch")
    assert p.mining_ready is True
    assert p.stratum_host == "solo-bch.2miners.com"
    assert p.stratum_port == 9393
    assert p.coinbase_enforce_fee_split is False
    assert p.coinbase_require_user_payout is False
    assert p.explorer_kind == "blockchair_bch"
