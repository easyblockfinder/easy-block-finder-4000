"""Shared machine settings form (wizard + Settings dialog)."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def _temp_row(spin: QSpinBox) -> QWidget:
    wrap = QWidget()
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(spin, 1)
    unit = QLabel("°C")
    unit.setObjectName("statKey")
    lay.addWidget(unit, 0)
    return wrap


class MachineSettingsForm(QWidget):
    """Intensity, thermal, CPU threads, battery, GPU pick — not per-coin."""

    changed = pyqtSignal()
    pick_gpu_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.lbl_hw = QLabel("Hardware: scanning…")
        self.lbl_hw.setObjectName("tagline")
        self.lbl_hw.setWordWrap(True)
        lay.addWidget(self.lbl_hw)

        form = QFormLayout()
        form.setSpacing(8)

        self.intensity = QSpinBox()
        self.intensity.setRange(1, 10)
        self.intensity.setMinimumHeight(34)
        self.intensity.setToolTip(
            "How hard the OpenCL/CPU engines push. "
            "1 = gentle (more sleep); 8–10 = max throughput, hotter GPU."
        )
        form.addRow("Intensity (1–10)", self.intensity)

        self.pause_temp = QSpinBox()
        self.pause_temp.setRange(50, 95)
        self.pause_temp.setMinimumHeight(34)
        self.pause_temp.setToolTip(
            "Mining pauses when sensor temperature reaches this value."
        )
        form.addRow("Pause mining at", _temp_row(self.pause_temp))

        self.resume_temp = QSpinBox()
        self.resume_temp.setRange(40, 90)
        self.resume_temp.setMinimumHeight(34)
        self.resume_temp.setToolTip(
            "Mining resumes after cooling to this temperature (must be below Pause)."
        )
        form.addRow("Resume mining at", _temp_row(self.resume_temp))

        self.cpu_threads = QSpinBox()
        self.cpu_threads.setRange(0, 256)
        self.cpu_threads.setMinimumHeight(34)
        self.cpu_threads.setToolTip("XMR RandomX threads. 0 = auto (recommended).")
        form.addRow("CPU threads (XMR, 0=auto)", self.cpu_threads)

        lay.addLayout(form)

        self.lbl_thermal_hint = QLabel("")
        self.lbl_thermal_hint.setObjectName("tagline")
        self.lbl_thermal_hint.setWordWrap(True)
        lay.addWidget(self.lbl_thermal_hint)

        self.pause_battery = QCheckBox("Stop XMR mining on battery power")
        lay.addWidget(self.pause_battery)

        self.lbl_gpu = QLabel("GPU bus/UUID: (auto on single GPU)")
        self.lbl_gpu.setObjectName("statKey")
        self.lbl_gpu.setWordWrap(True)
        lay.addWidget(self.lbl_gpu)

        self.btn_pick_gpu = QPushButton("Pick GPU (bus/UUID)")
        self.btn_pick_gpu.clicked.connect(self.pick_gpu_clicked.emit)
        lay.addWidget(self.btn_pick_gpu)

        for w in (
            self.intensity,
            self.pause_temp,
            self.resume_temp,
            self.cpu_threads,
            self.pause_battery,
        ):
            if isinstance(w, QSpinBox):
                w.valueChanged.connect(self._on_change)
            else:
                w.toggled.connect(self._on_change)

        self._refresh_thermal_hint()

    def _on_change(self, *_args: Any) -> None:
        self._refresh_thermal_hint()
        self.changed.emit()

    def _refresh_thermal_hint(self) -> None:
        pause = self.pause_temp.value()
        resume = self.resume_temp.value()
        tip = (
            f"Suggested laptop GPU: Pause 72–78°C, Resume ~{max(40, pause - 8)}°C. "
            f"Desktop can go a bit higher. Resume must stay below Pause "
            f"(now Pause={pause}°C, Resume={resume}°C)."
        )
        if resume >= pause:
            tip = (
                f"Resume ({resume}°C) must be lower than Pause ({pause}°C) "
                "or thermal restart will not work."
            )
        self.lbl_thermal_hint.setText(tip)

    def load_from(self, cfg: dict[str, Any]) -> None:
        self.intensity.setValue(int(cfg.get("intensity") or 1))
        self.pause_temp.setValue(int(cfg.get("pause_temp") or 65))
        self.resume_temp.setValue(int(cfg.get("resume_temp") or 55))
        self.cpu_threads.setValue(int(cfg.get("cpu_thread_limit") or 0))
        self.pause_battery.setChecked(bool(cfg.get("pause_on_battery", True)))
        bus = cfg.get("gpu_bus_id")
        uuid = cfg.get("gpu_uuid")
        if bus or uuid:
            self.lbl_gpu.setText(f"GPU bus/UUID: {bus or '—'} / {uuid or '—'}")
        else:
            self.lbl_gpu.setText("GPU bus/UUID: (auto on single GPU)")
        self._refresh_thermal_hint()

    def values(self) -> dict[str, Any]:
        return {
            "intensity": self.intensity.value(),
            "pause_temp": self.pause_temp.value(),
            "resume_temp": self.resume_temp.value(),
            "cpu_thread_limit": self.cpu_threads.value(),
            "pause_on_battery": self.pause_battery.isChecked(),
        }

    def set_hardware_summary(self, text: str) -> None:
        self.lbl_hw.setText(text or "Hardware: —")

    def apply_recommended_thermal(self, *, laptop: bool = True) -> None:
        # Explicit presets (not fresh-install defaults — those are 65 / 55).
        if laptop:
            self.pause_temp.setValue(75)
            self.resume_temp.setValue(67)
        else:
            self.pause_temp.setValue(82)
            self.resume_temp.setValue(74)
        if self.intensity.value() < 1:
            self.intensity.setValue(1)


def default_wizard_cfg(base: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = dict(base or {})
    cfg.setdefault("intensity", 4)
    cfg.setdefault("pause_temp", 65)
    cfg.setdefault("resume_temp", 55)
    cfg.setdefault("cpu_thread_limit", 0)
    cfg.setdefault("pause_on_battery", True)
    cfg.setdefault("scoreboard_overlay_enabled", True)
    return cfg
