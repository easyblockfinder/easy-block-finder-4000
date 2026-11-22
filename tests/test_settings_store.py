from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from ui import settings_store as ss  # noqa: E402


def test_save_and_load_address(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(ss, "_settings_path", lambda: path)
    ss.save_settings({"address": "bc1qexampleaddress0000000000000000000", "intensity": 3})
    data = ss.load_settings()
    assert data["address"].startswith("bc1q")
    assert data["intensity"] == 3
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "address" in raw


def test_existing_user_keeps_intensity_and_skips_wizard():
    """Pre-1.0.8 settings must not reset intensity or force the setup wizard."""
    old = {
        "intensity": 1,
        "pause_temp": 80,
        "resume_temp": 70,
        "address": "bc1qexampleaddress0000000000000000000",
        "network_wizard_done": True,
    }
    data = ss._normalize_loaded(old)
    assert data["intensity"] == 1
    assert data["pause_temp"] == 80
    assert data["resume_temp"] == 70
    assert data["setup_wizard_done"] is True
    assert data["scoreboard_overlay_enabled"] is True
    assert data["pool_by_network"] == {}
    assert data["auto_idle_mining"] is False
    assert data["idle_settings_configured"] is False
    assert data["idle_timeout_s"] == 150
    assert data["idle_active_pct"] == 10
    assert data["idle_idle_pct"] == 80


def test_fresh_install_gets_wizard_and_new_defaults():
    data = ss._normalize_loaded({})
    assert data["setup_wizard_done"] is False
    assert data["intensity"] == 4
    assert data["pause_temp"] == 75
    assert data["resume_temp"] == 60
