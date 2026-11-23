"""Temperature guard: default block + override."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from monitor import thermal_probe as tp  # noqa: E402
from ui.settings_store import DEFAULTS  # noqa: E402
from worker.controller import MiningController, MiningStats  # noqa: E402


def test_default_disallows_mine_without_temp():
    assert DEFAULTS.get("allow_mine_without_temp") is False


def test_probe_xmr_uses_cpu(monkeypatch):
    class FakeMon:
        available = True
        source_name = "WMI: fake"

        def __init__(self):
            pass

    monkeypatch.setattr("monitor.cpu_temp.CpuTemperatureMonitor", FakeMon)
    ok, detail = tp.probe_temperature_readable("xmr")
    assert ok is True
    assert "fake" in detail


def test_probe_xmr_unreadable(monkeypatch):
    class FakeMon:
        available = False
        source_name = "unreadable"

        def __init__(self):
            pass

    monkeypatch.setattr("monitor.cpu_temp.CpuTemperatureMonitor", FakeMon)
    ok, detail = tp.probe_temperature_readable("xmr")
    assert ok is False
    assert "unreadable" in detail.lower()


def test_probe_gpu_ok(monkeypatch):
    gpu = SimpleNamespace(bus_id="00000000:01:00.0", uuid="GPU-1", index=0, name="X")
    monkeypatch.setattr(
        "monitor.gpu_devices.resolve_gpu",
        lambda **k: gpu,
    )
    monkeypatch.setattr(
        "monitor.gpu_devices.temperature_for_bus",
        lambda bus: (72, f"NVML bus={bus}"),
    )
    ok, detail = tp.probe_temperature_readable("btc", gpu_bus_id=gpu.bus_id)
    assert ok is True
    assert "NVML" in detail


def test_probe_gpu_unreadable(monkeypatch):
    gpu = SimpleNamespace(bus_id="00000000:01:00.0", uuid="", index=0, name="X")
    monkeypatch.setattr("monitor.gpu_devices.resolve_gpu", lambda **k: gpu)
    monkeypatch.setattr(
        "monitor.gpu_devices.temperature_for_bus",
        lambda bus: (None, "NVML error: nope"),
    )
    ok, detail = tp.probe_temperature_readable("bch")
    assert ok is False
    assert "NVML" in detail or "unreadable" in detail.lower()


def test_abort_if_temp_required_blocks():
    c = MiningController()
    c.allow_mine_without_temp = False
    c.stats = MiningStats(temp_readable=False, thermal_source="none")
    assert c._abort_if_temp_required() is True
    assert "Blocked" in c.stats.status


def test_abort_if_temp_required_ignores_override():
    c = MiningController()
    c.allow_mine_without_temp = True  # ignored — thermal is mandatory
    c.stats = MiningStats(temp_readable=False, thermal_source="none")
    assert c._abort_if_temp_required() is True
    assert "Blocked" in c.stats.status


def test_abort_if_temp_ok():
    c = MiningController()
    c.allow_mine_without_temp = False
    c.stats = MiningStats(temp_readable=True, thermal_source="NVML")
    assert c._abort_if_temp_required() is False


def test_thermal_gate_pauses_when_sensor_lost(monkeypatch):
    c = MiningController()
    c.allow_mine_without_temp = True  # ignored
    c._resolved_gpu_bus = "00000000:01:00.0"
    c._paused = False
    monkeypatch.setattr(
        "monitor.gpu_devices.temperature_for_bus",
        lambda bus: (None, "gone"),
    )
    assert c._thermal_gate() is False
    assert c._paused is True
    assert c.stats.paused_thermal is True


def test_poll_temperature_updates_stats(monkeypatch):
    c = MiningController()
    c.gpu_bus_id = "00000000:01:00.0"
    c._resolved_gpu_bus = "00000000:01:00.0"
    monkeypatch.setattr(
        "monitor.gpu_devices.temperature_for_bus",
        lambda bus: (71, "NVML test"),
    )
    assert c.poll_temperature() == 71
    assert c.stats.gpu_temp == 71
    assert c.stats.temp_readable is True
