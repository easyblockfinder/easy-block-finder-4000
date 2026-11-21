from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from networks.pool_input import mask_secret, sanitize_host  # noqa: E402
from networks.pool_resolve import (  # noqa: E402
    normalize_pool_by_network,
    reset_pool_selection,
    resolve_default,
    resolve_pool,
)
from networks.profiles import get_profile  # noqa: E402


@pytest.mark.parametrize("nid", ["btc", "bch", "xmr", "rvn", "erg"])
def test_default_matches_profile(nid):
    prof = get_profile(nid)
    ep = resolve_default(nid)
    assert ep.mode == "default"
    assert ep.host == prof.stratum_host
    assert ep.port == prof.stratum_port
    assert ep.transport == "tcp"
    assert ep.password == (prof.password or "x")
    # username template equivalent
    wallet = "testwallet"
    assert ep.render_username(wallet) == prof.username_for(wallet)


def test_empty_settings_resolve_is_default():
    ep = resolve_pool("btc", {})
    assert ep.host == get_profile("btc").stratum_host
    assert ep.mode == "default"


def test_invalid_custom_falls_back_to_default():
    ep = resolve_pool(
        "btc",
        {"btc": {"mode": "custom", "custom": {"host": "", "port": 3333}}},
    )
    assert ep.mode == "default"
    assert ep.host == get_profile("btc").stratum_host


def test_valid_custom_shared_not_auto_solo():
    ep = resolve_pool(
        "btc",
        {
            "btc": {
                "mode": "custom",
                "custom": {
                    "host": "pool.example.com",
                    "port": 4444,
                    "transport": "tcp",
                    "username_format": "{wallet}",
                    "worker": "",
                    "password": "x",
                    "pool_kind": "shared",
                },
            }
        },
    )
    assert ep.mode == "custom"
    assert ep.host == "pool.example.com"
    assert ep.port == 4444
    assert ep.pool_kind == "shared"
    assert ep.validation_profile_id == "shared_pool"


def test_unknown_custom_kind():
    ep = resolve_pool(
        "bch",
        {
            "bch": {
                "mode": "custom",
                "custom": {
                    "host": "solo-bch.example.com",
                    "port": 9393,
                    "pool_kind": "unknown",
                },
            }
        },
    )
    assert ep.pool_kind == "unknown"
    assert ep.validation_profile_id == "unknown_custom"


def test_preset_missing_falls_back():
    ep = resolve_pool("btc", {"btc": {"mode": "preset", "preset_id": "nope"}})
    assert ep.mode == "default"


def test_reset_pool_selection():
    raw = {
        "btc": {"mode": "custom", "custom": {"host": "a.com", "port": 1}},
        "bch": {"mode": "custom", "custom": {"host": "b.com", "port": 2}},
    }
    # normalize first so structure is valid
    cleaned = normalize_pool_by_network(raw)
    out = reset_pool_selection("btc", cleaned)
    assert "btc" not in out
    assert "bch" in out


def test_sanitize_host_strips_url():
    assert sanitize_host("stratum+tcp://pool.example.com:3333") == "pool.example.com"
    with pytest.raises(ValueError):
        sanitize_host("pool.example.com; rm -rf /")


def test_mask_secret():
    assert mask_secret("secret") == "***"


def test_render_wallet_worker():
    ep = resolve_pool(
        "btc",
        {
            "btc": {
                "mode": "custom",
                "custom": {
                    "host": "pool.example.com",
                    "port": 3333,
                    "username_format": "{wallet}.{worker}",
                    "worker": "rig1",
                    "pool_kind": "solo",
                },
            }
        },
    )
    assert ep.render_username("bc1qtest") == "bc1qtest.rig1"
