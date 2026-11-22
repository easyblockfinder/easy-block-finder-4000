"""Tools → Mining Diagnostics — read-only session / hardware snapshot."""

from __future__ import annotations

from typing import Any

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_meta import APP_NAME, APP_VERSION_LABEL, load_app_icon


class MiningDiagnosticsDialog(QDialog):
    def __init__(
        self,
        report_text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Mining Diagnostics — {APP_NAME}")
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.setMinimumSize(560, 420)

        lay = QVBoxLayout(self)
        title = QLabel("Mining diagnostics")
        title.setFont(QFont("Bahnschrift", 14, QFont.Weight.Bold))
        lay.addWidget(title)
        note = QLabel(
            f"{APP_VERSION_LABEL} — snapshot of connection, activity, and hardware. "
            "Copy this text when reporting an issue."
        )
        note.setObjectName("tagline")
        note.setWordWrap(True)
        lay.addWidget(note)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Cascadia Mono", 10))
        self.view.setPlainText(report_text)
        lay.addWidget(self.view, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
            | QDialogButtonBox.StandardButton.Save
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setText("Copy to clipboard")
            save_btn.clicked.connect(self._copy)
        buttons.rejected.connect(self.reject)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        lay.addWidget(buttons)

    def _copy(self) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.view.toPlainText())


def build_diagnostics_text(
    *,
    cfg: dict[str, Any],
    network_id: str,
    profile_name: str,
    engine_kind: str,
    stats: Any,
    idle_state: str,
    idle_s: float | None,
) -> str:
    lines = [
        f"App: {APP_VERSION_LABEL}",
        f"Network: {network_id} ({profile_name})",
        f"Engine: {engine_kind}",
        f"Idle session: {idle_state}",
        f"User idle seconds: {idle_s if idle_s is not None else 'n/a'}",
        "",
        "--- Live stats ---",
        f"Connected: {getattr(stats, 'connected', False)}",
        f"Status: {getattr(stats, 'status', '')}",
        f"Device: {getattr(stats, 'device_name', '')}",
        f"Hashrate: {getattr(stats, 'hashrate', 0)}",
        f"Temp: {getattr(stats, 'temperature', None)}",
        f"Activity mode: {getattr(stats, 'activity_mode', 'off')}",
        f"Activity scale: {getattr(stats, 'activity_scale', 1.0)}",
        f"Activity UI: {getattr(stats, 'activity_ui', '')}",
        f"Paused thermal: {getattr(stats, 'paused_thermal', False)}",
        f"Paused idle: {getattr(stats, 'paused_idle', False)}",
        f"Test mode: {getattr(stats, 'test_mode', False)}",
        "",
        "--- Idle settings ---",
        f"Configured: {cfg.get('idle_settings_configured')}",
        f"Timeout s: {cfg.get('idle_timeout_s')}",
        f"While using PC %: {cfg.get('idle_active_pct')}",
        f"While AFK %: {cfg.get('idle_idle_pct')}",
        "",
        "--- Machine ---",
        f"Intensity: {cfg.get('intensity')}",
        f"Pause/Resume °C: {cfg.get('pause_temp')} / {cfg.get('resume_temp')}",
        f"CPU threads: {cfg.get('cpu_thread_limit')}",
        f"Pause on battery: {cfg.get('pause_on_battery')}",
        f"GPU bus/uuid: {cfg.get('gpu_bus_id')} / {cfg.get('gpu_uuid')}",
    ]
    return "\n".join(lines)
