from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.block_store import NETWORK_UNKNOWN, migrate_block_record  # noqa: E402


def test_legacy_1_address_not_forced_btc():
    rec = migrate_block_record(
        {
            "hash": "11" * 32,
            "payout_address": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
        }
    )
    assert rec["network_id"] == NETWORK_UNKNOWN


def test_legacy_3_address_not_forced_btc():
    rec = migrate_block_record(
        {
            "hash": "22" * 32,
            "payout_address": "3J98t1WpEZ73CNmYviecrnyiWrnqRhWNLy",
        }
    )
    assert rec["network_id"] == NETWORK_UNKNOWN


def test_bc1_still_btc():
    rec = migrate_block_record(
        {
            "hash": "33" * 32,
            "payout_address": "bc1qar0srrr7xfkvy5l643lydnw9re59gxgem9wg5z",
        }
    )
    assert rec["network_id"] == "btc"


def test_explicit_network_preserved():
    rec = migrate_block_record(
        {"hash": "44" * 32, "network_id": "bch", "payout_address": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"}
    )
    assert rec["network_id"] == "bch"


def test_btchunter_origin_btc():
    rec = migrate_block_record(
        {
            "hash": "55" * 32,
            "legacy_btc_hunter": True,
            "payout_address": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
        }
    )
    assert rec["network_id"] == "btc"


def test_bad_inferred_legacy_downgraded():
    # Onceki errorli migration: 1… + inferred → unknown’a cek
    rec = migrate_block_record(
        {
            "hash": "66" * 32,
            "network_id": "btc",
            "network_id_inferred": True,
            "payout_address": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
        }
    )
    assert rec["network_id"] == NETWORK_UNKNOWN
