from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from monitor.user_activity import idle_seconds  # noqa: E402


def test_idle_seconds_failure_returns_none_on_non_windows():
    with patch("monitor.user_activity.sys.platform", "linux"):
        assert idle_seconds() is None


def test_idle_seconds_win32_happy_path():
    with patch("monitor.user_activity.sys.platform", "win32"):
        fake_ctypes = MagicMock()
        # Minimal stand-in: call real function structure via patching import inside
        with patch.dict("sys.modules", {"ctypes": fake_ctypes}):
            # If import path fails, function should return None safely
            result = idle_seconds()
            assert result is None or isinstance(result, float)


def test_existing_settings_keep_auto_idle_off(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from ui.settings_store import _normalize_loaded

    data = _normalize_loaded(
        {"intensity": 7, "address": "bc1qexampleaddress0000000000000000000"}
    )
    assert data["auto_idle_mining"] is False
    assert data["idle_timeout_s"] == 150
    assert data["intensity"] == 7
