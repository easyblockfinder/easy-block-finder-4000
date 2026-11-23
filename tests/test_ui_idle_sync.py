"""Natural session endinde Start again acilir — MainWindow olusturmadan method testi."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from networks.profiles import get_profile  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from worker.idle_session import IdleSessionState  # noqa: E402


def _fake_window() -> SimpleNamespace:
    """MainWindow._sync_idle_controls_if_needed for thin stub."""
    w = SimpleNamespace()
    w._stop_busy = False
    w._idle_state = IdleSessionState.STOPPED
    w._network_id = "btc"
    w._profile = get_profile("btc")
    w._cfg = {}
    w.controller = SimpleNamespace(
        _stop_failed=False,
        is_running=MagicMock(return_value=False),
    )
    w.start_btn = SimpleNamespace(
        _en=False,
        isEnabled=lambda: w.start_btn._en,
        setEnabled=lambda v: setattr(w.start_btn, "_en", bool(v)),
    )
    w.stop_btn = SimpleNamespace(
        _en=True,
        isEnabled=lambda: w.stop_btn._en,
        setEnabled=lambda v: setattr(w.stop_btn, "_en", bool(v)),
    )
    w.idle_start_btn = SimpleNamespace(setEnabled=MagicMock())
    w.game_btn = SimpleNamespace(setEnabled=MagicMock())
    w.address_edit = SimpleNamespace(setEnabled=MagicMock())
    w.test_mode = SimpleNamespace(setEnabled=MagicMock())
    w.btn_change_network = SimpleNamespace(setEnabled=MagicMock())
    w.donate_enable = SimpleNamespace(setEnabled=MagicMock())
    w.donate_percent = SimpleNamespace(setEnabled=MagicMock())
    w.donate_address_edit = SimpleNamespace(setEnabled=MagicMock())
    w._idle_session_active = MagicMock(return_value=False)
    w._stop_idle_session_to_stopped = MagicMock()
    w._set_session_controls_locked = MainWindow._set_session_controls_locked.__get__(
        w, MainWindow
    )
    w._sync_idle_controls_if_needed = MainWindow._sync_idle_controls_if_needed.__get__(
        w, MainWindow
    )
    w._refresh_search_strategy_ui = MagicMock()
    return w


def test_sync_idle_controls_reenables_start():
    w = _fake_window()
    w._sync_idle_controls_if_needed()
    assert w.start_btn.isEnabled() is True
    assert w.stop_btn.isEnabled() is False
    w.address_edit.setEnabled.assert_called_with(True)


def test_sync_idle_skips_when_stop_failed():
    w = _fake_window()
    w.controller._stop_failed = True
    w._sync_idle_controls_if_needed()
    assert w.start_btn.isEnabled() is False
    assert w.stop_btn.isEnabled() is True


def test_sync_idle_skips_when_running():
    w = _fake_window()
    w.controller.is_running = MagicMock(return_value=True)
    w._sync_idle_controls_if_needed()
    assert w.start_btn.isEnabled() is False
    assert w.stop_btn.isEnabled() is True
