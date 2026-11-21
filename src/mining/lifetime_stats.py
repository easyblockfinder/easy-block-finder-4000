"""Per-network lifetime attempt counters (pool-agnostic; survives restarts)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app_meta import APP_DATA_DIRNAME
from networks.profiles import NETWORK_ORDER, normalize_network_id


def _local_app_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def _path() -> Path:
    folder = _local_app_data() / APP_DATA_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "lifetime_stats.json"


def load_lifetime_stats() -> dict[str, int]:
    path = _path()
    if not path.is_file():
        return {nid: 0 for nid in NETWORK_ORDER}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {nid: 0 for nid in NETWORK_ORDER}
    out = {nid: 0 for nid in NETWORK_ORDER}
    if not isinstance(data, dict):
        return out
    attempts = data.get("attempts_by_network")
    if not isinstance(attempts, dict):
        return out
    for nid, val in attempts.items():
        key = normalize_network_id(str(nid))
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out[key] = n
    return out


def get_lifetime_attempts(network_id: str) -> int:
    return int(load_lifetime_stats().get(normalize_network_id(network_id), 0))


def add_lifetime_attempts(network_id: str, delta: int) -> int:
    """Add delta hashes to lifetime counter; return new total."""
    d = max(0, int(delta))
    if d <= 0:
        return get_lifetime_attempts(network_id)
    nid = normalize_network_id(network_id)
    stats = load_lifetime_stats()
    stats[nid] = int(stats.get(nid, 0)) + d
    _save(stats)
    return int(stats[nid])


def _save(attempts_by_network: dict[str, int]) -> None:
    path = _path()
    payload: dict[str, Any] = {
        "attempts_by_network": {
            nid: int(attempts_by_network.get(nid, 0)) for nid in NETWORK_ORDER
        }
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix="lifetime_", suffix=".json", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        tmp_path.replace(path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
