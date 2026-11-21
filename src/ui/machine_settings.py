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

        idle_title = QLabel("Automatic Idle Mining")
        idle_title.setObjectName("sectionTitle")
        lay.addWidget(idle_title)

        self.auto_idle = QCheckBox("Reduce mining while I use the PC; raise when idle")
        self.auto_idle.setToolTip(
            "Uses Windows last-input time only (no keylogging). "
            "Default off — existing mining behavior unchanged until you enable it. "
            "Manual Stop and temperature protection always win."
        )
        lay.addWidget(self.auto_idle)

        idle_form = QFormLayout()
        idle_form.setSpacing(8)
        self.idle_timeout = QSpinBox()
        self.idle_timeout.setRange(5, 3600)
        self.idle_timeout.setSuffix(" s")
        self.idle_timeout.setMinimumHeight(34)
        self.idle_timeout.setToolTip(
            "Seconds without keyboard/mouse before IDLE MODE (default 150)."
        )
        idle_form.addRow("Idle timeout", self.idle_timeout)

        self.idle_active_pct = QSpinBox()
        self.idle_active_pct.setRange(0, 100)
        self.idle_active_pct.setSuffix(" %")
        self.idle_active_pct.setMinimumHeight(34)
        self.idle_active_pct.setToolTip(
            "Work scale while you are active, as % of your configured intensity/threads "
            "(not hardware max). 0 = pause hashing."
        )
        idle_form.addRow("Active intensity", self.idle_active_pct)

        self.idle_idle_pct = QSpinBox()
        self.idle_idle_pct.setRange(0, 100)
        self.idle_idle_pct.setSuffix(" %")
        self.idle_idle_pct.setMinimumHeight(34)
        self.idle_idle_pct.setToolTip(
            "Work scale after idle timeout, as % of your configured capacity. "
            "100% = full configured intensity/threads."
        )
        idle_form.addRow("Idle intensity", self.idle_idle_pct)
        lay.addLayout(idle_form)

        self.lbl_idle_note = QLabel(
            "BTC/BCH: percentages finely scale your Intensity (1–10) ceiling via batch/sleep. "
            "XMR: 0% = HTTP pause (pool stays); any %>0 resumes at your CPU thread limit "
            "(intermediate % is not faked). "
            "RVN/ERG (Rigel): ACTIVE pauses / IDLE resumes at configured capacity "
            "(pool may reconnect; DAG may rebuild)."
        )
        self.lbl_idle_note.setObjectName("tagline")
        self.lbl_idle_note.setWordWrap(True)
        lay.addWidget(self.lbl_idle_note)

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
            self.auto_idle,
            self.idle_timeout,
            self.idle_active_pct,
            self.idle_idle_pct,
        ):
            if isinstance(w, QSpinBox):
                w.valueChanged.connect(self._on_change)
            else:
                w.toggled.connect(self._on_change)

        self._refresh_thermal_hint()
        self._sync_idle_enabled()
        self.auto_idle.toggled.connect(self._sync_idle_enabled)

    def _sync_idle_enabled(self, *_args: Any) -> None:
        on = self.auto_idle.isChecked()
        for w in (self.idle_timeout, self.idle_active_pct, self.idle_idle_pct):
            w.setEnabled(on)

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
        self.auto_idle.setChecked(bool(cfg.get("auto_idle_mining", False)))
        self.idle_timeout.setValue(int(cfg.get("idle_timeout_s") or 150))
        self.idle_active_pct.setValue(int(cfg.get("idle_active_pct") if cfg.get("idle_active_pct") is not None else 10))
        self.idle_idle_pct.setValue(int(cfg.get("idle_idle_pct") if cfg.get("idle_idle_pct") is not None else 100))
        bus = cfg.get("gpu_bus_id")
        uuid = cfg.get("gpu_uuid")
        if bus or uuid:
            self.lbl_gpu.setText(f"GPU bus/UUID: {bus or '—'} / {uuid or '—'}")
        else:
            self.lbl_gpu.setText("GPU bus/UUID: (auto on single GPU)")
        self._refresh_thermal_hint()
        self._sync_idle_enabled()

    def values(self) -> dict[str, Any]:
        return {
            "intensity": self.intensity.value(),
            "pause_temp": self.pause_temp.value(),
            "resume_temp": self.resume_temp.value(),
            "cpu_thread_limit": self.cpu_threads.value(),
            "pause_on_battery": self.pause_battery.isChecked(),
            "auto_idle_mining": self.auto_idle.isChecked(),
            "idle_timeout_s": self.idle_timeout.value(),
            "idle_active_pct": self.idle_active_pct.value(),
            "idle_idle_pct": self.idle_idle_pct.value(),
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
