"""First-run / on-demand consent before downloading official miners."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from engines.miner_catalog import consent_body_for_miners


class MinerDownloadConsentDialog(QDialog):
    def __init__(self, miner_ids: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Miner download consent")
        self.setMinimumSize(560, 420)
        root = QVBoxLayout(self)

        title = QLabel("Allow download of official mining engines?")
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: 700; font-size: 14px;")
        root.addWidget(title)

        hint = QLabel(
            "Only the engine needed for your current network will be downloaded. "
            "Nothing is installed into the app zip; files go to your AppData folder "
            "after SHA-256 verification."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText(consent_body_for_miners(miner_ids))
        body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        root.addWidget(body, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Allow download")
        buttons.button(QDialogButtonBox.StandardButton.No).setText("Deny")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


def ask_miner_download_consent(parent, miner_ids: list[str]) -> bool:
    dlg = MinerDownloadConsentDialog(miner_ids, parent)
    return dlg.exec() == QDialog.DialogCode.Accepted
