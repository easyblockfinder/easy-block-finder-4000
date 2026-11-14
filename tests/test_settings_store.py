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
