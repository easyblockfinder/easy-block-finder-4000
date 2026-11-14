"""NetworkProfile registry ve ayar senkronu."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from networks.profiles import (  # noqa: E402
    get_profile,
    list_profiles,
    normalize_network_id,
)
from ui.settings_store import load_settings, save_settings  # noqa: E402


def test_five_networks_in_order():
    ids = [p.id for p in list_profiles()]
    assert ids == ["btc", "bch", "xmr", "rvn", "erg"]


def test_all_five_networks_ready():
    assert get_profile("btc").mining_ready is True
    assert get_profile("bch").mining_ready is True
    assert get_profile("xmr").mining_ready is True
    assert get_profile("xmr").username_for("ABC") == "solo:ABC"
    assert get_profile("rvn").mining_ready is True
    assert get_profile("erg").mining_ready is True
    assert get_profile("erg").stratum_port == 9999


def test_btc_stats_url():
    url = get_profile("btc").stats_url_for("bc1qtest")
    assert url == "https://raw.stats.ckpool.org/users/bc1qtest"


def test_bch_stats_and_username_canonicalize_cashaddr():
    p = get_profile("bch")
    bare = "qpsclskpllcnx8czg7z4d53z6xmnr950fgh2t27x78"
    canon = f"bitcoincash:{bare}"
    assert p.pool_identity(bare) == canon
    assert p.username_for(bare) == canon
    assert p.stats_url_for(bare) == f"https://solo-bch.2miners.com/account/{canon}"
    assert p.stats_url_for(canon.upper().replace("BITCOINCASH", "bitcoincash")) == (
        f"https://solo-bch.2miners.com/account/{canon}"
    )


def test_normalize_unknown():
    assert normalize_network_id("nope") == "btc"


def test_settings_address_by_network(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_settings(
        {
            "selected_network": "xmr",
            "address_by_network": {"xmr": "48abc", "btc": "bc1qbtc"},
            "address": "48abc",
        }
    )
    data = load_settings()
    assert data["selected_network"] == "xmr"
    assert data["address_by_network"]["xmr"] == "48abc"
    assert data["address_by_network"]["btc"] == "bc1qbtc"
    assert data["address"] == "48abc"
