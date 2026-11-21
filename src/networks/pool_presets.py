"""Curated pool presets. Only verified endpoints — Phase 1 ships empty lists;
Phase 2/5 add 2–3 verified presets per coin."""

from __future__ import annotations

from typing import Optional

from networks.pool_types import PoolPreset
from networks.profiles import NETWORK_ORDER, normalize_network_id

# Filled in later phases after host/port/TLS/username verification.
_PRESETS: dict[str, tuple[PoolPreset, ...]] = {nid: () for nid in NETWORK_ORDER}


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
