"""Settings dialog — machine-wide options (not per-coin address)."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from ui.machine_settings import MachineSettingsForm


class SettingsDialog(QDialog):
    def __init__(self, cfg: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings — Easy Block Finder 4000")
        self.setMinimumWidth(480)
        self._cfg = dict(cfg)

        lay = QVBoxLayout(self)
        title = QLabel("Machine settings")
        title.setObjectName("sectionTitle")
        lay.addWidget(title)
        note = QLabel(
            "These apply to every network. Payout addresses are set on the mining screen."
        )
        note.setObjectName("tagline")
        note.setWordWrap(True)
        lay.addWidget(note)

        self.form = MachineSettingsForm()
        self.form.load_from(self._cfg)
        lay.addWidget(self.form)
        from ui.wheel_guard import harden_wheel_widgets

        harden_wheel_widgets(self)

        self.chk_scoreboard = QCheckBox(
            "Show mini scoreboard overlay when minimized to the system tray"
        )
        self.chk_scoreboard.setChecked(
            bool(self._cfg.get("scoreboard_overlay_enabled", True))
        )
        self.chk_scoreboard.setToolTip(
            "When the main window is in the tray, a small LED scoreboard can stay "
            "on-screen (bottom-right). Turn off to hide it."
        )
        lay.addWidget(self.chk_scoreboard)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self) -> dict[str, Any]:
        out = self.form.values()
        out["scoreboard_overlay_enabled"] = self.chk_scoreboard.isChecked()
        return out
