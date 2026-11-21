from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from ui.settings_store import DEFAULTS, load_settings, save_settings  # noqa: E402


def test_missing_pool_by_network_defaults_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = load_settings()
    assert cfg["pool_by_network"] == {}
    assert "pool_by_network" in DEFAULTS


def test_legacy_settings_without_pool_key_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from app_meta import APP_DATA_DIRNAME

    app = tmp_path / APP_DATA_DIRNAME
    app.mkdir(parents=True)
    path = app / "settings.json"
    path.write_text(
        json.dumps({"selected_network": "btc", "address": "bc1qlegacy"}),
        encoding="utf-8",
    )
    cfg = load_settings()
    assert cfg["pool_by_network"] == {}
    assert cfg["address"] == "bc1qlegacy"


def test_save_roundtrip_pool_by_network(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = load_settings()
    cfg["pool_by_network"] = {
        "btc": {
            "mode": "custom",
            "custom": {
                "host": "pool.example.com",
                "port": 3333,
                "pool_kind": "shared",
            },
        }
    }
    save_settings(cfg)
    again = load_settings()
    assert again["pool_by_network"]["btc"]["mode"] == "custom"
    assert again["pool_by_network"]["btc"]["custom"]["host"] == "pool.example.com"
