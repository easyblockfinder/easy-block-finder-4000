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

        idle_title = QLabel("Idle Mode")
        idle_title.setObjectName("sectionTitle")
        self.lbl_idle_section = idle_title
        lay.addWidget(idle_title)

        idle_intro = QLabel(
            "Start Idle begins at “While using PC” intensity, then switches to "
            "“While AFK” after the timeout with no input. Normal Start ignores these."
        )
        idle_intro.setObjectName("tagline")
        idle_intro.setWordWrap(True)
        lay.addWidget(idle_intro)

        # Kept for load/save compatibility; Idle Mode is started from the main button.
        self.auto_idle = QCheckBox("Idle Mode settings ready")
        self.auto_idle.setToolTip(
            "Save Settings to mark Idle Mode as configured. "
            "Uses Windows last-input time only (no keylogging). "
            "Manual Stop and temperature protection always win."
        )
        self.auto_idle.setChecked(True)
        self.auto_idle.setVisible(False)

        idle_form = QFormLayout()
        idle_form.setSpacing(8)
        self.idle_timeout = QSpinBox()
        self.idle_timeout.setRange(5, 3600)
        self.idle_timeout.setSuffix(" s")
        self.idle_timeout.setMinimumHeight(34)
        self.idle_timeout.setToolTip(
            "Seconds without keyboard/mouse before switching to the AFK intensity."
        )
        idle_form.addRow("AFK timeout", self.idle_timeout)

        self.idle_active_pct = QSpinBox()
        self.idle_active_pct.setRange(0, 100)
        self.idle_active_pct.setSuffix(" %")
        self.idle_active_pct.setMinimumHeight(34)
        self.idle_active_pct.setToolTip(
            "While you use the PC (keyboard/mouse recently). "
            "0% = pause hashing; pool/engine stay up when possible."
        )
        idle_form.addRow("While using PC", self.idle_active_pct)

        self.idle_idle_pct = QSpinBox()
        self.idle_idle_pct.setRange(0, 100)
        self.idle_idle_pct.setSuffix(" %")
        self.idle_idle_pct.setMinimumHeight(34)
        self.idle_idle_pct.setToolTip(
            "While AFK (no input for the AFK timeout). "
            "100% = full configured intensity/threads. Not a guaranteed hashrate."
        )
        idle_form.addRow("While AFK", self.idle_idle_pct)
        lay.addLayout(idle_form)

        self.lbl_idle_note = QLabel(
            "“While using PC” applies when you are at the computer; “While AFK” after "
            "the timeout. BTC/BCH: duty-cycle. XMR/Rigel: binary pause/resume (% hidden)."
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
        from ui.wheel_guard import harden_wheel_widgets

        harden_wheel_widgets(self)

    def _sync_idle_enabled(self, *_args: Any) -> None:
        binary = bool(getattr(self, "_rigel_binary_idle", False))
        self.idle_timeout.setEnabled(True)
        show_pct = not binary
        for w in (self.idle_active_pct, self.idle_idle_pct):
            w.setEnabled(show_pct)
            w.setVisible(show_pct)

    def set_binary_idle_ui(self, binary: bool, *, engine: str = "") -> None:
        """Hide unsupported live % for XMR/Rigel; timeout remains."""
        self._rigel_binary_idle = bool(binary)
        eng = (engine or "").lower()
        if binary and eng == "xmr":
            self.lbl_idle_note.setText(
                "XMR (XMRig): Start Idle starts at While-using-PC (HTTP pause when you "
                "use the PC); after AFK timeout it resumes at your thread limit "
                "(no live % scaling)."
            )
        elif binary:
            self.lbl_idle_note.setText(
                "RVN/ERG (Rigel): Start Idle starts immediately; Using-PC pauses / "
                "AFK resumes at configured capacity (resume may reconnect pool / "
                "rebuild DAG)."
            )
        else:
            self.lbl_idle_note.setText(
                "BTC/BCH: “While using PC” then “While AFK” after timeout — "
                "adaptive duty-cycle under your Intensity ceiling "
                "(not guaranteed hashrate)."
            )
        self._sync_idle_enabled()

    def set_rigel_binary_idle(self, binary: bool) -> None:
        """Back-compat alias."""
        self.set_binary_idle_ui(binary, engine="rigel" if binary else "")

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
        self.pause_temp.setValue(int(cfg.get("pause_temp") or 75))
        self.resume_temp.setValue(int(cfg.get("resume_temp") or 60))
        self.cpu_threads.setValue(int(cfg.get("cpu_thread_limit") or 0))
        self.pause_battery.setChecked(bool(cfg.get("pause_on_battery", True)))
        configured = bool(cfg.get("idle_settings_configured", False)) or bool(
            cfg.get("auto_idle_mining", False)
        )
        self.auto_idle.setChecked(configured)
        self.idle_timeout.setValue(int(cfg.get("idle_timeout_s") or 150))
        self.idle_active_pct.setValue(
            int(
                cfg.get("idle_active_pct")
                if cfg.get("idle_active_pct") is not None
                else 10
            )
        )
        self.idle_idle_pct.setValue(
            int(
                cfg.get("idle_idle_pct")
                if cfg.get("idle_idle_pct") is not None
                else 80
            )
        )
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
            "auto_idle_mining": False,
            "idle_settings_configured": True,
            "idle_timeout_s": self.idle_timeout.value(),
            "idle_active_pct": self.idle_active_pct.value(),
            "idle_idle_pct": self.idle_idle_pct.value(),
        }

    def set_hardware_summary(self, text: str) -> None:
        self.lbl_hw.setText(text or "Hardware: —")

    def apply_recommended_thermal(self, *, laptop: bool = True) -> None:
        # Explicit presets (not fresh-install defaults — those are 75 / 60).
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
    cfg.setdefault("pause_temp", 75)
    cfg.setdefault("resume_temp", 60)
    cfg.setdefault("cpu_thread_limit", 0)
    cfg.setdefault("pause_on_battery", True)
    cfg.setdefault("scoreboard_overlay_enabled", True)
    return cfg
