"""Modal progress UI for official miner downloads (XMRig / Rigel)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


def _fmt_bytes(n: int) -> str:
    if n <= 0:
        return "0 B"
    for unit, div in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


class MinerDownloadProgressDialog(QDialog):
    def __init__(self, title: str = "Downloading miner", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(460, 300)
        self.setModal(True)
        self._failed = False
        self._busy = True
        root = QVBoxLayout(self)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("font-weight: 700; font-size: 13px;")
        self.lbl_title.setWordWrap(True)
        root.addWidget(self.lbl_title)

        self.lbl_status = QLabel("Starting…")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        root.addWidget(self.bar)

        self.lbl_bytes = QLabel("")
        self.lbl_bytes.setObjectName("tagline")
        root.addWidget(self.lbl_bytes)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(120)
        self.log.setPlaceholderText("Status log…")
        root.addWidget(self.log, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_close = QPushButton("Close")
        self.btn_close.setEnabled(False)
        self.btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_close)
        root.addLayout(row)

    def reject(self) -> None:  # noqa: N802
        # Block Esc / X while download is running
        if self._busy:
            return
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)

    def set_miner_title(self, name: str, index: int, total: int) -> None:
        if total > 1:
            self.lbl_title.setText(f"Downloading {name} ({index}/{total})")
        else:
            self.lbl_title.setText(f"Downloading {name}")

    def set_progress(
        self, phase: str, received: int, total: int | None, detail: str
    ) -> None:
        phase_label = {
            "check": "Checking local file",
            "download": "Downloading",
            "verify": "Verifying checksum",
            "extract": "Extracting",
            "done": "Done",
            "error": "Error",
        }.get(phase, phase)
        self.lbl_status.setText(detail.strip() if detail.strip() else phase_label)
        if detail.strip():
            # Avoid flooding the log on every download chunk
            if phase != "download" or received == 0 or (
                total and received >= total
            ):
                self._append_log(f"[{phase}] {detail.strip()}")
            elif phase == "download" and total and received > 0:
                # update status only; occasional log every ~10%
                pct = int(100 * received / total)
                if pct % 10 == 0:
                    self._append_log(
                        f"[download] {_fmt_bytes(received)} / {_fmt_bytes(total)} ({pct}%)"
                    )

        if phase == "download" and total and total > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(min(100, int(100 * received / total)))
            self.lbl_bytes.setText(f"{_fmt_bytes(received)} / {_fmt_bytes(total)}")
        elif phase in ("verify", "extract", "check"):
            self.bar.setRange(0, 0)
            self.lbl_bytes.setText("")
        elif phase == "done":
            self.bar.setRange(0, 100)
            self.bar.setValue(100)
            self.lbl_bytes.setText("")
        elif phase == "error":
            self.bar.setRange(0, 100)
            self.bar.setValue(0)
            self.lbl_bytes.setText("")

    def mark_success(self, summary: str = "Download complete.") -> None:
        self._failed = False
        self._busy = False
        self.lbl_status.setText(summary)
        self.lbl_status.setStyleSheet("")
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self._append_log(summary)
        self.btn_close.setEnabled(True)

    def mark_error(self, message: str) -> None:
        self._failed = True
        self._busy = False
        self.lbl_status.setText("Download failed — see details below.")
        self.lbl_status.setStyleSheet("color: #b71c1c; font-weight: 700;")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self._append_log(f"[error] {message}")
        self.btn_close.setEnabled(True)

    @property
    def failed(self) -> bool:
        return self._failed

    def append_log(self, line: str) -> None:
        self.log.appendPlainText(line)
        # Keep the latest status visible
        cursor = self.log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()
        bar = self.log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _append_log(self, line: str) -> None:
        self.append_log(line)
