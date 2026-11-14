"""Liability disclaimer when temperature cannot be read."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)


DISCLAIMER_TEXT = """TEMPERATURE UNREADABLE — NO AUTOMATIC THERMAL PROTECTION

This application cannot read a reliable CPU/GPU temperature for the selected network.
Without a temperature reading, the automatic pause/resume thermal guard will NOT run.

Continuing to mine may overheat or permanently damage your hardware, reduce component
lifespan, cause system instability, data loss, or create a fire risk.

BY CONTINUING YOU CONFIRM THAT:
• You understand automatic thermal protection is unavailable.
• You will monitor temperatures and system health yourself.
• You accept full responsibility for any damage, loss, or injury.
• The authors and distributors of Easy Block Finder 4000 are not liable for hardware
  damage, data loss, downtime, or any other consequence of mining without a temp guard.

If you are unsure, click Cancel and fix temperature monitoring (drivers / sensors) first.
"""


class ThermalDisclaimerDialog(QDialog):
    """
    Returns:
      Accepted + once  → mine once without guard
      Accepted + always → persist allow_mine_without_temp
      Rejected         → cancel start
    """

    RESULT_ONCE = 1
    RESULT_ALWAYS = 2

    def __init__(self, detail: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Temperature unreadable — liability notice")
        self.setMinimumSize(540, 480)
        self.choice = 0
        root = QVBoxLayout(self)

        title = QLabel("Cannot read temperature")
        title.setStyleSheet("font-weight: 700; font-size: 14px; color: #b71c1c;")
        root.addWidget(title)

        body = QPlainTextEdit()
        body.setReadOnly(True)
        text = DISCLAIMER_TEXT
        if detail.strip():
            text += "\nTechnical detail:\n" + detail.strip()
        body.setPlainText(text)
        root.addWidget(body, 1)

        self.ack = QCheckBox(
            "I have read this notice and accept full responsibility for continuing "
            "without automatic thermal protection."
        )
        self.ack.toggled.connect(self._sync_buttons)
        root.addWidget(self.ack)

        buttons = QDialogButtonBox()
        self.btn_once = buttons.addButton(
            "Continue once", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.btn_always = buttons.addButton(
            "Always allow (unsafe)", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.btn_cancel = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.btn_once.clicked.connect(lambda: self._finish(self.RESULT_ONCE))
        self.btn_always.clicked.connect(lambda: self._finish(self.RESULT_ALWAYS))
        self.btn_cancel.clicked.connect(self.reject)
        root.addWidget(buttons)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        ok = self.ack.isChecked()
        self.btn_once.setEnabled(ok)
        self.btn_always.setEnabled(ok)

    def _finish(self, choice: int) -> None:
        if not self.ack.isChecked():
            QMessageBox.information(
                self,
                "Acknowledgement required",
                "Tick the responsibility checkbox before continuing.",
            )
            return
        self.choice = choice
        self.accept()


def ask_thermal_disclaimer(parent, detail: str = "") -> int:
    """
    0 = cancel, 1 = once, 2 = always.
    """
    dlg = ThermalDisclaimerDialog(detail, parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return 0
    return int(dlg.choice)
