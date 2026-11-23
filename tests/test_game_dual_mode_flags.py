from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from worker.controller import MiningController  # noqa: E402


def test_refresh_session_kind_both():
    c = MiningController()
    c._auto_enabled = True
    c._game_enabled = True
    c._refresh_session_kind()
    assert c._session_kind == "both"
    assert c.is_auto_mode() and c.is_game_mode()


def test_refresh_session_kind_game_only():
    c = MiningController()
    c._auto_enabled = False
    c._game_enabled = True
    c._refresh_session_kind()
    assert c._session_kind == "game"


def test_gpu_share_prefers_lagging_side():
    """Scheduling invariant: prefer side with less accumulated GPU seconds."""
    auto_s, game_s = 1.0, 0.4
    prefer_game = game_s <= auto_s
    assert prefer_game is True
    auto_s, game_s = 0.2, 1.5
    prefer_game = game_s <= auto_s
    assert prefer_game is False


def test_game_gpu_only_when_board_open():
    c = MiningController()
    c._auto_enabled = True
    c._game_enabled = True
    c._game_board_open = False
    assert c._game_gpu_active() is False
    c.set_game_board_open(True)
    assert c._game_gpu_active() is True
    c.set_game_board_open(False)
    assert c._game_gpu_active() is False


def test_board_closed_means_auto_owns_intensity():
    """Closed board → Game GPU inactive → Automatic keeps full Intensity."""
    c = MiningController()
    c._auto_enabled = True
    c._game_enabled = True
    c.set_game_board_open(False)
    assert c._game_gpu_active() is False
    # Dual scheduling gate used by mine loop
    dual = c._game_gpu_active() and c._auto_enabled
    assert dual is False
    c.set_game_board_open(True)
    assert (c._game_gpu_active() and c._auto_enabled) is True
