from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from networks.pool_resolve import resolve_pool, stats_url_for_endpoint  # noqa: E402
from networks.profiles import get_profile  # noqa: E402


def test_xmr_kryptex_stats_url_wallet_without_solo_prefix():
    p = get_profile("xmr")
    addr = "4" + "A" * 94  # format testi; real checksum not
    url = p.stats_url_for(addr)
    assert url == f"https://pool.kryptex.com/xmr/miner/stats/{addr}"
    assert "/solo:" not in url
    assert p.username_for(addr) == f"solo:{addr}"
    assert p.explorer_kind == "none"


def test_rvn_erg_still_account_links_not_explorer():
    assert get_profile("rvn").explorer_kind == "none"
    assert "2miners.com/account/" in get_profile("rvn").stats_url_for("Raddr")
    assert get_profile("erg").explorer_kind == "none"


def test_xmr_default_and_kryptex_preset_use_kryptex_rewards():
    addr = "4" + "B" * 94
    default_ep = resolve_pool("xmr", {})
    assert "kryptex.com" in stats_url_for_endpoint(default_ep, addr)

    preset_ep = resolve_pool(
        "xmr",
        {"xmr": {"mode": "preset", "preset_id": "kryptex_xmr_eu"}},
    )
    assert "kryptex.com" in stats_url_for_endpoint(preset_ep, addr)


def test_xmr_custom_hashvault_has_no_rewards_url():
    addr = "4" + "C" * 94
    ep = resolve_pool(
        "xmr",
        {
            "xmr": {
                "mode": "custom",
                "custom": {
                    "host": "pool.hashvault.pro",
                    "port": 443,
                    "transport": "tls",
                    "username_format": "{wallet}",
                    "worker": "",
                    "password": "x",
                    "pool_kind": "unknown",
                },
            }
        },
    )
    assert ep.mode == "custom"
    assert ep.host == "pool.hashvault.pro"
    assert stats_url_for_endpoint(ep, addr) == ""
    # Must not fall back to Kryptex profile URL
    assert "kryptex" not in (ep.stats_url_template or "").lower()
