"""Shared machine settings form (wizard + Settings dialog)."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
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
    lay.setSpacing(6)
    lay.addWidget(spin, 1)
    unit = QLabel("°C")
    unit.setObjectName("statKey")
    lay.addWidget(unit, 0)
    return wrap


def _section(title: str, hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("settingsSection")
    card.setStyleSheet(
        "QFrame#settingsSection {"
        "  background: #f8fafc;"
        "  border: 1px solid #e2e8f0;"
        "  border-radius: 10px;"
        "}"
    )
    outer = QVBoxLayout(card)
    outer.setContentsMargins(12, 10, 12, 12)
    outer.setSpacing(8)
    head = QLabel(title)
    head.setObjectName("sectionTitle")
    outer.addWidget(head)
    if hint:
        note = QLabel(hint)
        note.setObjectName("tagline")
        note.setWordWrap(True)
        outer.addWidget(note)
    body = QVBoxLayout()
    body.setSpacing(8)
    outer.addLayout(body)
    return card, body


class MachineSettingsForm(QWidget):
    """Intensity, thermal, Idle Mode, GPU — machine-wide (not per-coin)."""

    changed = pyqtSignal()
    pick_gpu_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.lbl_hw = QLabel("Hardware: scanning…")
        self.lbl_hw.setObjectName("tagline")
        self.lbl_hw.setWordWrap(True)
        lay.addWidget(self.lbl_hw)

        # --- Mining load ---
        mining_card, mining_body = _section("Mining load")
        form = QFormLayout()
        form.setSpacing(8)
        form.setContentsMargins(0, 0, 0, 0)
        self.intensity = QSpinBox()
        self.intensity.setRange(1, 10)
        self.intensity.setMinimumHeight(34)
        self.intensity.setToolTip("1 = cooler / slower · 8–10 = max throughput")
        form.addRow("Intensity", self.intensity)
        self.cpu_threads = QSpinBox()
        self.cpu_threads.setRange(0, 256)
        self.cpu_threads.setMinimumHeight(34)
        self.cpu_threads.setToolTip("XMR RandomX threads. 0 = auto")
        form.addRow("CPU threads (XMR)", self.cpu_threads)
        mining_body.addLayout(form)
        self.pause_battery = QCheckBox("Pause XMR on battery")
        mining_body.addWidget(self.pause_battery)
        lay.addWidget(mining_card)

        # --- Temperature ---
        thermal_card, thermal_body = _section(
            "Temperature",
            "Resume must stay below Pause.",
        )
        tform = QFormLayout()
        tform.setSpacing(8)
        tform.setContentsMargins(0, 0, 0, 0)
        self.pause_temp = QSpinBox()
        self.pause_temp.setRange(50, 95)
        self.pause_temp.setMinimumHeight(34)
        tform.addRow("Pause at", _temp_row(self.pause_temp))
        self.resume_temp = QSpinBox()
        self.resume_temp.setRange(40, 90)
        self.resume_temp.setMinimumHeight(34)
        tform.addRow("Resume at", _temp_row(self.resume_temp))
        thermal_body.addLayout(tform)
        self.lbl_thermal_hint = QLabel("")
        self.lbl_thermal_hint.setObjectName("tagline")
        self.lbl_thermal_hint.setWordWrap(True)
        thermal_body.addWidget(self.lbl_thermal_hint)
        lay.addWidget(thermal_card)

        # --- Idle Mode ---
        idle_card, idle_body = _section(
            "Idle Mode",
            "Start Idle uses these. Normal Start ignores them.",
        )
        self.lbl_idle_section = idle_card  # focus target from main window
        self.auto_idle = QCheckBox("Idle Mode settings ready")
        self.auto_idle.setChecked(True)
        self.auto_idle.setVisible(False)
        idle_form = QFormLayout()
        idle_form.setSpacing(8)
        idle_form.setContentsMargins(0, 0, 0, 0)
        self.idle_timeout = QSpinBox()
        self.idle_timeout.setRange(5, 3600)
        self.idle_timeout.setSuffix(" s")
        self.idle_timeout.setMinimumHeight(34)
        idle_form.addRow("AFK timeout", self.idle_timeout)
        self.idle_active_pct = QSpinBox()
        self.idle_active_pct.setRange(0, 100)
        self.idle_active_pct.setSuffix(" %")
        self.idle_active_pct.setMinimumHeight(34)
        idle_form.addRow("While using PC", self.idle_active_pct)
        self.idle_idle_pct = QSpinBox()
        self.idle_idle_pct.setRange(0, 100)
        self.idle_idle_pct.setSuffix(" %")
        self.idle_idle_pct.setMinimumHeight(34)
        idle_form.addRow("While AFK", self.idle_idle_pct)
        idle_body.addLayout(idle_form)
        self.lbl_idle_note = QLabel("")
        self.lbl_idle_note.setObjectName("tagline")
        self.lbl_idle_note.setWordWrap(True)
        idle_body.addWidget(self.lbl_idle_note)
        lay.addWidget(idle_card)

        # --- GPU ---
        gpu_card, gpu_body = _section("GPU")
        self.lbl_gpu = QLabel("Auto (single GPU)")
        self.lbl_gpu.setObjectName("statKey")
        self.lbl_gpu.setWordWrap(True)
        gpu_body.addWidget(self.lbl_gpu)
        self.btn_pick_gpu = QPushButton("Choose GPU…")
        self.btn_pick_gpu.clicked.connect(self.pick_gpu_clicked.emit)
        gpu_body.addWidget(self.btn_pick_gpu)
        lay.addWidget(gpu_card)

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
        self.set_binary_idle_ui(False, engine="native")
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
        self._rigel_binary_idle = bool(binary)
        eng = (engine or "").lower()
        if binary and eng == "xmr":
            self.lbl_idle_note.setText(
                "XMR: Using-PC pauses hashing; AFK resumes at your thread limit."
            )
        elif binary:
            self.lbl_idle_note.setText(
                "RVN/ERG: Using-PC pauses; AFK resumes (pool may reconnect)."
            )
        else:
            self.lbl_idle_note.setText(
                "BTC/BCH: duty-cycle under Intensity (not a guaranteed hashrate)."
            )
        self._sync_idle_enabled()

    def set_rigel_binary_idle(self, binary: bool) -> None:
        self.set_binary_idle_ui(binary, engine="rigel" if binary else "")

    def _on_change(self, *_args: Any) -> None:
        self._refresh_thermal_hint()
        self.changed.emit()

    def _refresh_thermal_hint(self) -> None:
        pause = self.pause_temp.value()
        resume = self.resume_temp.value()
        if resume >= pause:
            self.lbl_thermal_hint.setText(
                f"Invalid: Resume ({resume}°C) must be below Pause ({pause}°C)."
            )
        else:
            self.lbl_thermal_hint.setText(
                f"Laptop tip: Pause 72–78°C · Resume ~{max(40, pause - 8)}°C"
            )

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
            self.lbl_gpu.setText(f"{bus or '—'} / {uuid or '—'}")
        else:
            self.lbl_gpu.setText("Auto (single GPU)")
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
