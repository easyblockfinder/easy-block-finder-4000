"""User settings — payout address and UI preferences persist on disk."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from app_meta import APP_DATA_DIRNAME, LEGACY_APP_DATA_DIRNAMES
from mining.app_donation import default_app_donation, normalize_app_donation
from networks.profiles import NETWORK_ORDER, normalize_network_id


def _local_app_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def _settings_path() -> Path:
    folder = _local_app_data() / APP_DATA_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "settings.json"


def _legacy_settings_candidates() -> list[Path]:
    base = _local_app_data()
    out: list[Path] = []
    for name in LEGACY_APP_DATA_DIRNAMES:
        out.append(base / name / "settings.json")
    return out


DEFAULTS: dict[str, Any] = {
    "address": "",
    "selected_network": "btc",
    "address_by_network": {nid: "" for nid in NETWORK_ORDER},
    "intensity": 1,
    "pause_temp": 80,
    "resume_temp": 70,
    "test_mode": False,
    "window_width": 760,
    "window_height": 720,
    "cpu_thread_limit": 0,
    "pause_on_battery": True,
    "allow_mine_without_temp": False,
    "miner_download_consent": False,
    "gpu_bus_id": None,
    "gpu_uuid": None,
    "xmrig_donate_level": 1,
    "app_donation": default_app_donation(),
}


def _normalize_loaded(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULTS)
    out["address_by_network"] = dict(DEFAULTS["address_by_network"])
    out["app_donation"] = default_app_donation()
    for k, v in data.items():
        if k == "address_by_network" and isinstance(v, dict):
            for nid in NETWORK_ORDER:
                if nid in v and isinstance(v[nid], str):
                    out["address_by_network"][nid] = v[nid]
        elif k == "app_donation":
            out["app_donation"] = normalize_app_donation(v)
        elif k in DEFAULTS and k not in ("address_by_network", "app_donation"):
            out[k] = v
    out["selected_network"] = normalize_network_id(str(out.get("selected_network") or "btc"))
    # Migrate legacy single 'address' field into btc
    legacy_addr = str(out.get("address") or "").strip()
    if legacy_addr and not out["address_by_network"].get("btc"):
        out["address_by_network"]["btc"] = legacy_addr
    nid = out["selected_network"]
    out["address"] = out["address_by_network"].get(nid) or (
        legacy_addr if nid == "btc" else ""
    )
    out["app_donation"] = normalize_app_donation(out.get("app_donation"))
    return out


def _maybe_migrate_settings() -> None:
    """Copy legacy settings into the new AppData folder once."""
    path = _settings_path()
    if path.is_file():
        return
    for legacy in _legacy_settings_candidates():
        if legacy.is_file():
            try:
                shutil.copy2(legacy, path)
            except OSError:
                continue
            return


def load_settings() -> dict[str, Any]:
    _maybe_migrate_settings()
    path = _settings_path()
    if not path.is_file():
        for legacy in _legacy_settings_candidates():
            if legacy.is_file():
                path = legacy
                break
    if not path.is_file():
        return _normalize_loaded({})
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return _normalize_loaded(raw)
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return _normalize_loaded({})


def save_settings(updates: dict[str, Any]) -> None:
    data = load_settings()
    if "address_by_network" in updates and isinstance(updates["address_by_network"], dict):
        merged = dict(data["address_by_network"])
        merged.update(updates["address_by_network"])
        data["address_by_network"] = merged
        updates = {k: v for k, v in updates.items() if k != "address_by_network"}
    if "app_donation" in updates:
        data["app_donation"] = normalize_app_donation(updates["app_donation"])
        updates = {k: v for k, v in updates.items() if k != "app_donation"}
    data.update(updates)
    if "selected_network" in data:
        data["selected_network"] = normalize_network_id(str(data["selected_network"]))
    # Keep flat 'address' in sync with selected network
    nid = data["selected_network"]
    if "address" in updates:
        data["address_by_network"][nid] = str(updates["address"] or "").strip()
    data["address"] = data["address_by_network"].get(nid, "")
    data["app_donation"] = normalize_app_donation(data.get("app_donation"))
    path = _settings_path()
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def settings_file() -> Path:
    return _settings_path()
