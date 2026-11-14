"""GPU temperature reading with NVML."""

from __future__ import annotations

import warnings
from typing import Optional


def _import_pynvml():
    """nvidia-ml-py; the old 'pynvml' meta-package should not print FutureWarning."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=".*pynvml package is deprecated.*",
            category=FutureWarning,
        )
        import pynvml  # noqa: WPS433 — official binding module name

        return pynvml


class GpuTemperatureMonitor:
    def __init__(self) -> None:
        self.available = False
        self._handle = None
        self._pynvml = None
        try:
            # Official package: nvidia-ml-py (module name is still pynvml)
            pynvml = _import_pynvml()
            pynvml.nvmlInit()
            self._pynvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.available = True
        except Exception:
            self.available = False
            self._handle = None

    def read_celsius(self) -> Optional[int]:
        if not self.available or self._pynvml is None or self._handle is None:
            return None
        try:
            return int(
                self._pynvml.nvmlDeviceGetTemperature(
                    self._handle, self._pynvml.NVML_TEMPERATURE_GPU
                )
            )
        except Exception:
            return None

    def close(self) -> None:
        if self._pynvml and self.available:
            try:
                self._pynvml.nvmlShutdown()
            except Exception:
                pass
        self.available = False
