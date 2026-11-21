from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from networks.pool_presets import get_preset, list_presets  # noqa: E402
from networks.pool_resolve import resolve_pool  # noqa: E402
from networks.pool_validation import get_validation_profile  # noqa: E402
from networks.profiles import get_profile  # noqa: E402


def test_btc_has_verified_presets():
    presets = list_presets("btc")
    assert 2 <= len(presets) <= 3
    ids = {p.id for p in presets}
    assert "ckpool_eu" in ids
    assert "public_pool_solo" in ids
    for p in presets:
        assert p.transport == "tcp"
        assert p.port > 0
        assert p.host
        assert p.pool_kind in ("solo", "shared")
        assert get_validation_profile(p.validation_profile_id).id == p.validation_profile_id


def test_bch_has_verified_regionals():
    presets = list_presets("bch")
    assert 2 <= len(presets) <= 3
    hosts = {p.host for p in presets}
    assert "us-solo-bch.2miners.com" in hosts
    assert "asia-solo-bch.2miners.com" in hosts
    for p in presets:
        assert p.port == 9393
        assert p.pool_kind == "solo"


def test_preset_resolve_does_not_change_default():
    default = get_profile("btc")
    ep = resolve_pool("btc", {})
    assert ep.host == default.stratum_host
    assert ep.port == default.stratum_port
    ep2 = resolve_pool(
        "btc", {"btc": {"mode": "preset", "preset_id": "ckpool_eu"}}
    )
    assert ep2.host == "eusolo.ckpool.org"
    assert ep2.mode == "preset"
    assert ep2.pool_kind == "solo"


def test_public_pool_username_without_worker():
    ep = resolve_pool(
        "btc",
        {"btc": {"mode": "preset", "preset_id": "public_pool_solo"}},
    )
    assert ep.render_username("bc1qabc") == "bc1qabc"
    ep_w = resolve_pool(
        "btc",
        {
            "btc": {
                "mode": "preset",
                "preset_id": "public_pool_solo",
                "worker": "rig1",
            }
        },
    )
    assert ep_w.render_username("bc1qabc") == "bc1qabc.rig1"


def test_external_coins_have_empty_presets_for_now():
    assert list_presets("xmr") == []
    assert get_preset("rvn", "anything") is None
