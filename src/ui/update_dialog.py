"""Update available / progress dialogs."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from update.service import UpdateOffer


def _fmt_size(n: int) -> str:
    if n <= 0:
        return "unknown size"
    for unit, div in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


class UpdateAvailableDialog(QDialog):
    def __init__(self, offer: UpdateOffer, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update available")
        self.setMinimumSize(520, 420)
        self._choice = "later"
        root = QVBoxLayout(self)

        title = QLabel(
            f"Easy Block Finder 4000 {offer.remote_version} is available\n"
            f"(you have {offer.current_version})"
        )
        title.setStyleSheet("font-weight: 700; font-size: 14px;")
        title.setWordWrap(True)
        root.addWidget(title)

        meta = QLabel(
            f"Package: {offer.zip_name}  ·  {_fmt_size(offer.zip_size)}\n"
            f"Source: GitHub Releases (easyblockfinder/easy-block-finder-4000)"
        )
        meta.setWordWrap(True)
        root.addWidget(meta)

        notes_lbl = QLabel("Release notes")
        notes_lbl.setStyleSheet("font-weight: 600;")
        root.addWidget(notes_lbl)
        notes = QPlainTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(offer.notes.strip() or "(No release notes provided.)")
        root.addWidget(notes, 1)

        hint = QLabel(
            "Update Now downloads the signed package, verifies minisign + SHA-256, "
            "stops mining, then applies files via an external updater. "
            "Your settings, wallet addresses, and AppData miners are kept. "
            "Windows Defender is not disabled."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        row = QHBoxLayout()
        btn_later = QPushButton("Later")
        btn_update = QPushButton("Update Now")
        btn_update.setDefault(True)
        btn_later.clicked.connect(self._later)
        btn_update.clicked.connect(self._now)
        row.addStretch(1)
        row.addWidget(btn_later)
        row.addWidget(btn_update)
        root.addLayout(row)

    def _later(self) -> None:
        self._choice = "later"
        self.reject()

    def _now(self) -> None:
        self._choice = "now"
        self.accept()

    @property
    def choice(self) -> str:
        return self._choice


class UpdateProgressDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Downloading update")
        self.setMinimumWidth(420)
        self.setModal(True)
        root = QVBoxLayout(self)
        self.lbl = QLabel("Preparing…")
        self.lbl.setWordWrap(True)
        root.addWidget(self.lbl)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        root.addWidget(self.bar)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)  # cancel mid-verify is unsafe; kept for future
        self.btn_cancel.setVisible(False)
        root.addWidget(self.btn_cancel, alignment=Qt.AlignmentFlag.AlignRight)

    def set_phase(self, phase: str, received: int, total: int | None) -> None:
        labels = {
            "manifest": "Downloading SHA256SUMS…",
            "signature": "Downloading signature…",
            "package": "Downloading package…",
            "verify": "Verifying signature and checksum…",
            "extract": "Extracting package…",
            "stop": "Stopping mining…",
            "apply": "Launching updater…",
        }
        self.lbl.setText(labels.get(phase, phase))
        if total and total > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(min(100, int(100 * received / total)))
        else:
            self.bar.setRange(0, 0)
