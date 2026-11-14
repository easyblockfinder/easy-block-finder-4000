"""CPU ACPI nonesa NVML GPU yedegi."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from monitor import cpu_temp as cpu_temp_mod  # noqa: E402
from monitor.cpu_temp import CpuTemperatureMonitor  # noqa: E402


def test_nvml_fallback_when_acpi_unsupported(monkeypatch):
    monkeypatch.setattr(CpuTemperatureMonitor, "_try_wmi_acpi", lambda self: False)
    monkeypatch.setattr(CpuTemperatureMonitor, "_try_win32com_acpi", lambda self: False)
    monkeypatch.setattr(CpuTemperatureMonitor, "_try_libre_ohm", lambda self, *a, **k: False)

    fake = MagicMock()
    fake.available = True
    fake.read_celsius.return_value = 61
    fake.close = MagicMock()

    class FakeGpu:
        def __init__(self):
            self.available = True

        def read_celsius(self):
            return 61

        def close(self):
            pass

    monkeypatch.setattr(
        "monitor.temp.GpuTemperatureMonitor",
        FakeGpu,
    )
    # import path inside method uses monitor.temp
    import monitor.temp as temp_mod

    monkeypatch.setattr(temp_mod, "GpuTemperatureMonitor", FakeGpu)

    m = CpuTemperatureMonitor()
    assert m.available is True
    assert "NVML" in m.source_name
    assert m.read_celsius() == 61


def test_acpi_preferred_over_nvml(monkeypatch):
    def fake_wmi(self):
        self._reader = ("wmi_acpi", MagicMock())
        self.source_name = "WMI: MSAcpi_ThermalZoneTemperature"
        self.available = True
        return True

    monkeypatch.setattr(CpuTemperatureMonitor, "_try_wmi_acpi", fake_wmi)
    called = {"n": 0}

    def no_nvml(self):
        called["n"] += 1
        return False

    monkeypatch.setattr(CpuTemperatureMonitor, "_try_nvml_gpu_fallback", no_nvml)
    m = CpuTemperatureMonitor()
    assert m.available is True
    assert called["n"] == 0
    assert "WMI" in m.source_name
