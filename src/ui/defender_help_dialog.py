"""Simple Windows Security guidance — no Defender bypass."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from engines.windows_security import (
    defender_steps_plain,
    miners_exclusion_path,
    open_exclusion_script_elevated,
    open_windows_security,
)


class DefenderHelpDialog(QDialog):
    def __init__(self, miner_label: str = "XMRig", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Windows Security — miner blocked")
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)

        body = QLabel(defender_steps_plain(miner_label))
        body.setWordWrap(True)
        root.addWidget(body)

        row = QHBoxLayout()
        btn_copy = QPushButton("Copy folder path")
        btn_sec = QPushButton("Open Windows Security")
        btn_uac = QPushButton("Add exclusion (UAC)")
        btn_copy.clicked.connect(self._copy_path)
        btn_sec.clicked.connect(lambda: open_windows_security())
        btn_uac.clicked.connect(self._run_uac)
        row.addWidget(btn_copy)
        row.addWidget(btn_sec)
        row.addWidget(btn_uac)
        root.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def _copy_path(self) -> None:
        from PyQt6.QtWidgets import QApplication

        path = str(miners_exclusion_path())
        QApplication.clipboard().setText(path)
        QMessageBox.information(self, "Copied", f"Folder path copied:\n{path}")

    def _run_uac(self) -> None:
        if open_exclusion_script_elevated():
            QMessageBox.information(
                self,
                "Administrator prompt",
                "Approve the Windows UAC prompt if shown.\n"
                "That only adds a folder exclusion — Defender stays on.",
            )
        else:
            QMessageBox.warning(
                self,
                "Could not start helper",
                "Run manually as Administrator:\n"
                "scripts\\add_defender_exclusion.ps1",
            )


def show_defender_help(parent, miner_label: str = "XMRig") -> None:
    DefenderHelpDialog(miner_label, parent).exec()
