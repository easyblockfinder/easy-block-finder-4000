"""Mandatory consent dialog before entering Scratch Mining Game Mode."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)


WARNING_TITLE = "Interactive Mining Mode"

WARNING_BODY = (
    "Scratch Mining is a manual, interactive mining experience.\n\n"
    "Unlike automatic mining, hashing only occurs when you select a nonce tile.\n\n"
    "Time spent selecting tiles, loading new jobs, displaying animations, and "
    "interacting with the game may reduce your effective hashrate and your "
    "probability of finding a block within a given period.\n\n"
    "Every tile represents real nonce values, and every mining result comes from "
    "genuine SHA256d calculations.\n\n"
    "Tile selection does not provide a mathematical advantage over automatic mining.\n\n"
    "No rewards are guaranteed."
)


class ScratchGameConsentDialog(QDialog):
    """Every Game Mode entry requires a fresh confirmation (no 'don't show again')."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(WARNING_TITLE)
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        title = QLabel(WARNING_TITLE)
        title.setObjectName("sectionTitle")
        lay.addWidget(title)
        body = QLabel(WARNING_BODY)
        body.setWordWrap(True)
        body.setObjectName("tagline")
        lay.addWidget(body)
        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        enter = buttons.addButton(
            "I Understand — Enter Game Mode",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        cancel.clicked.connect(self.reject)
        enter.clicked.connect(self.accept)
        lay.addWidget(buttons)
