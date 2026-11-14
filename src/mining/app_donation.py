"""Legacy mining-slice donation — REMOVED.

Mining is never redirected to donation addresses.
Manual donations: ui.donate_dialog + donate_addresses.
This module only loads old setting keys harmlessly.
"""

from __future__ import annotations

from typing import Any

from networks.profiles import NETWORK_ORDER

FULL_REWARD_WARNING = (
    "Mining donations were removed. Use the Donate button at the top for support; "
    "donations do not affect mining."
)

DEFAULT_PERCENT = 0.0
DEFAULT_CYCLE_S = 600.0


def empty_donation_addresses() -> dict[str, str]:
    return {nid: "" for nid in NETWORK_ORDER}


def default_app_donation() -> dict[str, Any]:
    return {
        "enabled": False,
        "percent": 0.0,
        "ack_full_reward_warning": False,
        "donation_address_by_network": empty_donation_addresses(),
    }


def normalize_app_donation(raw: Any) -> dict[str, Any]:
    """Always disabled — no mining redirection."""
    return default_app_donation()


def donation_address_for(cfg: dict[str, Any], network_id: str) -> str:
    return ""


def is_effectively_enabled(cfg: dict[str, Any], network_id: str) -> bool:
    return False


def in_donation_slice(
    elapsed_s: float,
    percent: float,
    *,
    cycle_s: float = DEFAULT_CYCLE_S,
) -> bool:
    return False
