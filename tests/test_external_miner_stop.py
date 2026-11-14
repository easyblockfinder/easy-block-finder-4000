from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.rigel_runner import RigelRunner  # noqa: E402
from engines.xmrig_runner import XmrigRunner  # noqa: E402
from worker.controller import MiningController  # noqa: E402


def _zombie_proc() -> MagicMock:
    proc = MagicMock()
    proc.poll.return_value = None  # hâlâ still running

    def _wait(timeout=None):
        raise TimeoutError("wait timeout")

    proc.wait.side_effect = _wait
    proc.terminate.return_value = None
    proc.kill.side_effect = OSError("kill failed")
    return proc


def test_xmrig_stop_refuses_clear_when_alive():
    r = XmrigRunner(Path("xmrig.exe"), host="h", port=1, username="u")
    r._proc = _zombie_proc()
    with pytest.raises(RuntimeError, match="did not exit|did not close|still running"):
        r.stop(timeout_s=0.1)
    assert r._proc is not None
    assert r.is_running() is True


def test_rigel_stop_refuses_clear_when_alive():
    r = RigelRunner(
        Path("rigel.exe"),
        algorithm="kawpow",
        coin="rvn",
        host="h",
        port=1,
        username="u",
    )
    r._proc = _zombie_proc()
    with pytest.raises(RuntimeError, match="did not exit|did not close|still running"):
        r.stop(timeout_s=0.1)
    assert r._proc is not None


def test_xmrig_stop_ok_clears_ref():
    r = XmrigRunner(Path("xmrig.exe"), host="h", port=1, username="u")
    proc = MagicMock()
    proc.poll.side_effect = [None, 0]
    proc.wait.return_value = 0
    r._proc = proc
    r.stop(timeout_s=1.0)
    assert r._proc is None
    assert r.is_running() is False


def test_controller_is_running_includes_external(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    c._thread = None
    c._preparing = False
    c._stop_failed = False
    z = XmrigRunner(Path("xmrig.exe"), host="h", port=1, username="u")
    z._proc = _zombie_proc()
    c._xmrig = z
    assert c.is_running() is True
