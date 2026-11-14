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


def _fake_window() -> SimpleNamespace:
    """MainWindow._sync_idle_controls_if_needed for thin stub."""
    w = SimpleNamespace()
    w._stop_busy = False
    w._profile = get_profile("btc")
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
    w.address_edit = SimpleNamespace(setEnabled=MagicMock())
    w.test_mode = SimpleNamespace(setEnabled=MagicMock())
    w.btn_change_network = SimpleNamespace(setEnabled=MagicMock())
    w.donate_enable = SimpleNamespace(setEnabled=MagicMock())
    w.donate_percent = SimpleNamespace(setEnabled=MagicMock())
    w.donate_address_edit = SimpleNamespace(setEnabled=MagicMock())
    w._sync_idle_controls_if_needed = MainWindow._sync_idle_controls_if_needed.__get__(
        w, MainWindow
    )
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
