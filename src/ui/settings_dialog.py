"""Settings dialog — machine-wide options (not per-coin address)."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import (
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

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self) -> dict[str, Any]:
        return self.form.values()
