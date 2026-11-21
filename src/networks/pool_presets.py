"""Curated pool presets — only endpoints verified from official pool docs.

Verification notes (2026-11-21):
- BTC CKPool regionals: listed on https://solo.ckpool.org/ under Manual stratum servers
  (port 3333, username = BTC address, password any). Same fee model as default
  stratum.ckpool.org (~2%).
- BTC Public Pool solo: https://web.public-pool.io/ Stratum V1
  stratum+tcp://public-pool.io:3333 (NOT 13333 PPLNS). Username = BTC address[.worker].
- BCH 2Miners regionals: https://solo-bch.2miners.com/help — US/Asia :9393,
  username = BCH address, password x. Same account-wallet payout model as EU default.

Defaults remain NetworkProfile endpoints (not duplicated here as presets).
TLS custom endpoints are supported via StratumClient cert verification.
TLS presets can be added after the same host:port docs are verified; custom TLS
to public-pool.io:4333 (official) is available in the pool picker.
"""

from __future__ import annotations

from typing import Optional

from networks.pool_types import PoolPreset
from networks.profiles import NETWORK_ORDER, normalize_network_id

_PRESETS: dict[str, tuple[PoolPreset, ...]] = {
    "btc": (
        PoolPreset(
            id="ckpool_eu",
            network_id="btc",
            display_name="CKPool Germany (eusolo)",
            host="eusolo.ckpool.org",
            port=3333,
            transport="tcp",
            username_format="{wallet}",
            password="x",
            pool_kind="solo",
            validation_profile_id="ckpool_btc_solo",
            stats_url_template="https://raw.stats.ckpool.org/users/{address}",
            notes="Official CKPool regional (solo.ckpool.org). ~2% fee. SOLO.",
        ),
        PoolPreset(
            id="ckpool_us_east",
            network_id="btc",
            display_name="CKPool US East (uesolo)",
            host="uesolo.ckpool.org",
            port=3333,
            transport="tcp",
            username_format="{wallet}",
            password="x",
            pool_kind="solo",
            validation_profile_id="ckpool_btc_solo",
            stats_url_template="https://raw.stats.ckpool.org/users/{address}",
            notes="Official CKPool regional (solo.ckpool.org). ~2% fee. SOLO.",
        ),
        PoolPreset(
            id="public_pool_solo",
            network_id="btc",
            display_name="Public Pool (solo 0%)",
            host="public-pool.io",
            port=3333,
            transport="tcp",
            username_format="{wallet}.{worker}",
            password="x",
            pool_kind="solo",
            validation_profile_id="public_pool_btc_solo",
            stats_url_template="",
            notes=(
                "Official web.public-pool.io solo port 3333 — not PPLNS 13333. "
                "Advertised 0% fee. SOLO."
            ),
        ),
    ),
    "bch": (
        PoolPreset(
            id="2miners_bch_us",
            network_id="bch",
            display_name="2Miners BCH SOLO (USA)",
            host="us-solo-bch.2miners.com",
            port=9393,
            transport="tcp",
            username_format="{wallet}",
            password="x",
            pool_kind="solo",
            validation_profile_id="bch_pool_wallet",
            stats_url_template="https://solo-bch.2miners.com/account/{address}",
            notes="Official 2Miners help table. Account-wallet payout. SOLO.",
        ),
        PoolPreset(
            id="2miners_bch_asia",
            network_id="bch",
            display_name="2Miners BCH SOLO (Asia)",
            host="asia-solo-bch.2miners.com",
            port=9393,
            transport="tcp",
            username_format="{wallet}",
            password="x",
            pool_kind="solo",
            validation_profile_id="bch_pool_wallet",
            stats_url_template="https://solo-bch.2miners.com/account/{address}",
            notes="Official 2Miners help table. Account-wallet payout. SOLO.",
        ),
    ),
    "xmr": (
        PoolPreset(
            id="kryptex_xmr_eu",
            network_id="xmr",
            display_name="Kryptex XMR (Europe)",
            host="xmr-eu.kryptex.network",
            port=7029,
            transport="tcp",
            username_format="solo:{wallet}",
            password="x",
            pool_kind="solo",
            validation_profile_id="external_default",
            stats_url_template="",
            notes="Official pool.kryptex.com/xmr regional TCP :7029. SOLO via solo:wallet.",
        ),
        PoolPreset(
            id="kryptex_xmr_us",
            network_id="xmr",
            display_name="Kryptex XMR (North America)",
            host="xmr-us.kryptex.network",
            port=7029,
            transport="tcp",
            username_format="solo:{wallet}",
            password="x",
            pool_kind="solo",
            validation_profile_id="external_default",
            stats_url_template="",
            notes="Official pool.kryptex.com/xmr regional TCP :7029. SOLO via solo:wallet.",
        ),
    ),
    "rvn": (
        PoolPreset(
            id="2miners_rvn_us",
            network_id="rvn",
            display_name="2Miners RVN SOLO (USA)",
            host="us-solo-rvn.2miners.com",
            port=7070,
            transport="tcp",
            username_format="{wallet}",
            password="x",
            pool_kind="solo",
            validation_profile_id="external_default",
            stats_url_template="https://solo-rvn.2miners.com/account/{address}",
            notes="Official solo-rvn.2miners.com/help GPU port :7070. SOLO.",
        ),
        PoolPreset(
            id="2miners_rvn_asia",
            network_id="rvn",
            display_name="2Miners RVN SOLO (Asia)",
            host="asia-solo-rvn.2miners.com",
            port=7070,
            transport="tcp",
            username_format="{wallet}",
            password="x",
            pool_kind="solo",
            validation_profile_id="external_default",
            stats_url_template="https://solo-rvn.2miners.com/account/{address}",
            notes="Official solo-rvn.2miners.com/help GPU port :7070. SOLO.",
        ),
    ),
    "erg": (
        PoolPreset(
            id="2miners_erg_us",
            network_id="erg",
            display_name="2Miners ERG SOLO (USA)",
            host="us-solo-erg.2miners.com",
            port=9999,
            transport="tcp",
            username_format="{wallet}",
            password="x",
            pool_kind="solo",
            validation_profile_id="external_default",
            stats_url_template="https://solo-erg.2miners.com/account/{address}",
            notes="Official solo-erg.2miners.com/help GPU port :9999. SOLO.",
        ),
        PoolPreset(
            id="2miners_erg_asia",
            network_id="erg",
            display_name="2Miners ERG SOLO (Asia)",
            host="asia-solo-erg.2miners.com",
            port=9999,
            transport="tcp",
            username_format="{wallet}",
            password="x",
            pool_kind="solo",
            validation_profile_id="external_default",
            stats_url_template="https://solo-erg.2miners.com/account/{address}",
            notes="Official solo-erg.2miners.com/help GPU port :9999. SOLO.",
        ),
    ),
}

# Ensure every network key exists.
for _nid in NETWORK_ORDER:
    _PRESETS.setdefault(_nid, ())


def list_presets(network_id: str) -> list[PoolPreset]:
    nid = normalize_network_id(network_id)
    return list(_PRESETS.get(nid, ()))


def get_preset(network_id: str, preset_id: str) -> Optional[PoolPreset]:
    nid = normalize_network_id(network_id)
    key = (preset_id or "").strip()
    for p in _PRESETS.get(nid, ()):
        if p.id == key:
            return p
    return None
