"""Isi pause + temp=None → mining does not open. Thermal is mandatory."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from worker.controller import MiningController  # noqa: E402


def test_thermal_gate_paused_temp_none_stays_paused(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    c._paused = True
    c.pause_temp = 80
    c.resume_temp = 70
    c._resolved_gpu_bus = ""
    c._temp.read_celsius = lambda: None  # type: ignore[method-assign]
    assert c._thermal_gate() is False
    assert c._paused is True
    assert c.stats.paused_thermal is True


def test_thermal_gate_unpaused_temp_none_always_pauses(tmp_path, monkeypatch):
    """Sensor loss must pause — override is never honored."""
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    c._paused = False
    c.allow_mine_without_temp = True  # ignored
    c._resolved_gpu_bus = ""
    c._temp.read_celsius = lambda: None  # type: ignore[method-assign]
    assert c._thermal_gate() is False
    assert c._paused is True
    assert c.stats.paused_thermal is True


def test_thermal_gate_over_threshold_pauses(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    c._paused = False
    c.pause_temp = 75
    c.resume_temp = 60
    c._resolved_gpu_bus = ""
    c._temp.read_celsius = lambda: 80  # type: ignore[method-assign]
    assert c._thermal_gate() is False
    assert c._paused is True
    assert c.stats.paused_thermal is True


def test_thermal_gate_resume_when_cool(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    c._paused = True
    c.pause_temp = 80
    c.resume_temp = 70
    c._resolved_gpu_bus = ""
    c._temp.read_celsius = lambda: 65  # type: ignore[method-assign]
    assert c._thermal_gate() is True
    assert c._paused is False
    assert c.stats.paused_thermal is False
