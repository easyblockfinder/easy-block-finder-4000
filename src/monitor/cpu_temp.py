"""CPU temperature — multiple sources; NVML GPU fallback if unsuccessful."""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


class CpuTemperatureMonitor:
    def __init__(self) -> None:
        self.available = False
        self.source_name = "yok"
        self._reader: Any = None
        self._probe()

    def _probe(self) -> None:
        if self._try_wmi_acpi():
            return
        if self._try_win32com_acpi():
            return
        if self._try_libre_ohm("root\\LibreHardwareMonitor", "LibreHardwareMonitor"):
            return
        if self._try_libre_ohm("root\\OpenHardwareMonitor", "OpenHardwareMonitor"):
            return
        if self._try_nvml_gpu_fallback():
            return
        self.available = False
        self.source_name = "unreadable"
        self._reader = None

    def _try_wmi_acpi(self) -> bool:
        try:
            import wmi  # type: ignore

            c = wmi.WMI(namespace="root\\wmi")
            zones = c.MSAcpi_ThermalZoneTemperature()
            if zones:
                self._reader = ("wmi_acpi", c)
                self.source_name = "WMI: MSAcpi_ThermalZoneTemperature"
                self.available = True
                return True
        except Exception as exc:
            log.debug("WMI ACPI no temperature: %s", exc)
        return False

    def _try_win32com_acpi(self) -> bool:
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
            svc = locator.ConnectServer(".", "root\\wmi")
            zones = list(svc.ExecQuery("SELECT * FROM MSAcpi_ThermalZoneTemperature"))
            if zones:
                self._reader = ("win32com_acpi", None)
                self.source_name = "WMI/COM: MSAcpi_ThermalZoneTemperature"
                self.available = True
                return True
        except Exception as exc:
            log.debug("Win32com ACPI no temperature: %s", exc)
        return False

    def _try_libre_ohm(self, namespace: str, label: str) -> bool:
        try:
            import wmi  # type: ignore

            c = wmi.WMI(namespace=namespace)
            sensors = list(c.Sensor())
            # CPU paket / Tctl tercih
            preferred = []
            any_temp = []
            for s in sensors:
                stype = str(getattr(s, "SensorType", "") or "")
                if stype.lower() != "temperature":
                    continue
                name = str(getattr(s, "Name", "") or "")
                val = getattr(s, "Value", None)
                if val is None:
                    continue
                any_temp.append((name, float(val)))
                low = name.lower()
                if any(
                    k in low
                    for k in ("package", "tctl", "cpu", "core max", "ccd")
                ):
                    preferred.append((name, float(val)))
            pick = preferred[0] if preferred else (any_temp[0] if any_temp else None)
            if pick is None:
                return False
            self._reader = ("libre_ohm", namespace, pick[0])
            self.source_name = f"{label}: {pick[0]}"
            self.available = True
            return True
        except Exception as exc:
            log.debug("%s no temperature: %s", label, exc)
        return False

    def _try_nvml_gpu_fallback(self) -> bool:
        """If the CPU doesn't have ACPI, then at least thermal protection/UI with NVML."""
        try:
            from monitor.temp import GpuTemperatureMonitor

            gpu = GpuTemperatureMonitor()
            if not gpu.available or gpu.read_celsius() is None:
                try:
                    gpu.close()
                except Exception:
                    pass
                return False
            self._reader = ("nvml_gpu", gpu)
            self.source_name = "NVML GPU (CPU ACPI bu sistemde yok)"
            self.available = True
            return True
        except Exception as exc:
            log.debug("NVML GPU no standby temperature: %s", exc)
        return False

    def read_celsius(self) -> Optional[int]:
        if not self.available or self._reader is None:
            return None
        kind = self._reader[0]
        try:
            if kind == "wmi_acpi":
                c = self._reader[1]
                zones = c.MSAcpi_ThermalZoneTemperature()
                if not zones:
                    return None
                raw = int(zones[0].CurrentTemperature)
                return int(raw / 10 - 273.15)
            if kind == "win32com_acpi":
                import pythoncom
                import win32com.client

                pythoncom.CoInitialize()
                locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
                svc = locator.ConnectServer(".", "root\\wmi")
                zones = list(
                    svc.ExecQuery("SELECT * FROM MSAcpi_ThermalZoneTemperature")
                )
                if not zones:
                    return None
                raw = int(zones[0].CurrentTemperature)
                return int(raw / 10 - 273.15)
            if kind == "libre_ohm":
                _, namespace, sensor_name = self._reader
                import wmi  # type: ignore

                c = wmi.WMI(namespace=namespace)
                for s in c.Sensor():
                    if str(getattr(s, "SensorType", "") or "").lower() != "temperature":
                        continue
                    if str(getattr(s, "Name", "") or "") != sensor_name:
                        continue
                    val = getattr(s, "Value", None)
                    if val is None:
                        return None
                    return int(float(val))
                return None
            if kind == "nvml_gpu":
                gpu = self._reader[1]
                return gpu.read_celsius()
        except Exception:
            log.debug("read_celsius hata", exc_info=True)
            return None
        return None
