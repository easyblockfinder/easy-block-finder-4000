"""Optional wizard page: CPU / GPU detection status + capacity handoff."""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app_meta import APP_NAME, APP_VERSION_LABEL, load_app_logo_pixmap
from monitor.hardware_report import HardwareReport, build_hardware_report
from ui.busy_indicator import BusyIndicator


def _status_word(ok: bool) -> str:
    return "DETECTED" if ok else "NOT DETECTED"


class _DetectWorker(QThread):
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            self.finished_ok.emit(build_hardware_report(include_vram=False))
        except Exception as exc:
            self.failed.emit(str(exc))


class HardwareDetectPage(QWidget):
    continue_clicked = pyqtSignal()  # apply capacity → network list
    back_clicked = pyqtSignal()  # return without capacity probe

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("root")
        self._report: HardwareReport | None = None
        self._detect_worker: _DetectWorker | None = None
        self._busy_locked = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        logo = QLabel()
        pix = load_app_logo_pixmap(440, 96)
        if not pix.isNull():
            logo.setPixmap(pix)
        else:
            logo.setText(APP_NAME)
            logo.setFont(QFont("Bahnschrift", 24, QFont.Weight.Bold))
        layout.addWidget(logo)

        ver = QLabel(APP_VERSION_LABEL)
        ver.setObjectName("tagline")
        layout.addWidget(ver)

        title = QLabel("Hardware detection")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        sub = QLabel(
            "Before choosing a network, EBF4000 checks CPU and GPU availability. "
            "Networks that need missing hardware are disabled with a reason."
        )
        sub.setObjectName("tagline")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        self._busy = BusyIndicator()
        layout.addWidget(self._busy)

        self.panel = QFrame()
        self.panel.setObjectName("panel")
        self._panel_layout = QVBoxLayout(self.panel)
        self._panel_layout.setContentsMargins(14, 12, 14, 12)
        self._panel_layout.setSpacing(10)
        layout.addWidget(self.panel)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setObjectName("tagline")
        layout.addWidget(self.lbl_summary)

        self.btn_rescan = QPushButton("Scan again")
        self.btn_rescan.clicked.connect(self.refresh)
        layout.addWidget(self.btn_rescan)

        self.btn_continue = QPushButton("Run capacity check — back to network list")
        self.btn_continue.setObjectName("startBtn")
        self.btn_continue.clicked.connect(self._on_continue)
        layout.addWidget(self.btn_continue)

        self.btn_skip = QPushButton("← Back to network list")
        self.btn_skip.clicked.connect(self.back_clicked.emit)
        layout.addWidget(self.btn_skip)
        layout.addStretch(1)

        self.refresh()

    def report(self) -> HardwareReport | None:
        return self._report

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Lock page + show spinner (capacity check or detect scan)."""
        self._busy_locked = busy
        if busy:
            self._busy.show_busy(message or "Please wait…")
        else:
            self._busy.hide_busy()
            if message:
                self.lbl_summary.setText(message)
        self._set_actions_enabled(not busy)

    def _set_actions_enabled(self, enabled: bool) -> None:
        self.btn_rescan.setEnabled(enabled)
        self.btn_continue.setEnabled(enabled)
        self.btn_skip.setEnabled(enabled)

    def _on_continue(self) -> None:
        if self._busy_locked:
            return
        self.continue_clicked.emit()

    def refresh(self) -> None:
        if self._detect_worker is not None and self._detect_worker.isRunning():
            return
        self.set_busy(True, "Scanning CPU / GPU (OpenCL & NVIDIA)…")
        while self._panel_layout.count():
            item = self._panel_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.lbl_summary.setText("Detecting hardware…")

        worker = _DetectWorker(parent=self)
        self._detect_worker = worker

        def _ok(report: object) -> None:
            if isinstance(report, HardwareReport):
                self._apply_report(report)
            self.set_busy(False)

        def _fail(err: str) -> None:
            self.lbl_summary.setText(f"Hardware scan failed: {err}")
            self.set_busy(False)

        worker.finished_ok.connect(_ok)
        worker.failed.connect(_fail)
        worker.start()

    def _apply_report(self, r: HardwareReport) -> None:
        self._report = r
        while self._panel_layout.count():
            item = self._panel_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        self._panel_layout.addWidget(
            self._section(
                "CPU",
                r.cpu_ok,
                r.cpu_label,
                r.cpu_detail,
                extra_lines=[],
            )
        )
        opencl_lines = [f"• {d.name} — {d.detail}" for d in r.opencl_devices[:6]]
        self._panel_layout.addWidget(
            self._section(
                "GPU (OpenCL) — BTC / BCH",
                r.opencl_ok,
                "OpenCL GPU" if r.opencl_ok else "OpenCL GPU",
                r.opencl_detail,
                extra_lines=opencl_lines,
            )
        )
        nv_lines = [f"• {d.name} — {d.detail}" for d in r.nvidia_devices[:6]]
        self._panel_layout.addWidget(
            self._section(
                "GPU (NVIDIA CUDA) — RVN / ERG",
                r.nvidia_ok,
                "NVIDIA GPU" if r.nvidia_ok else "NVIDIA GPU",
                r.nvidia_detail,
                extra_lines=nv_lines,
            )
        )

        disabled = [nid.upper() for nid, reason in r.network_blocks.items() if reason]
        if r.deps_mode == "cpu-only":
            self.lbl_summary.setText(
                "This session is CPU-only (start.bat cpu). Only XMR can be selected."
            )
        elif disabled:
            self.lbl_summary.setText(
                "Currently unavailable from detection alone: "
                + ", ".join(disabled)
                + ". Next step also checks GPU VRAM capacity for KawPoW / Autolykos2."
            )
        else:
            self.lbl_summary.setText(
                "CPU and GPU probes look usable. Next step verifies VRAM capacity "
                "for Ravencoin / Ergo."
            )

    def _section(
        self,
        title: str,
        ok: bool,
        label: str,
        detail: str,
        *,
        extra_lines: list[str],
    ) -> QWidget:
        box = QFrame()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 4, 0, 8)
        v.setSpacing(4)
        status = _status_word(ok)
        color = "#1b5e20" if ok else "#b71c1c"
        head = QLabel(f"{title}:  {status}")
        head.setStyleSheet(f"font-weight: 700; color: {color};")
        v.addWidget(head)
        body = QLabel(f"{label}\n{detail}")
        body.setWordWrap(True)
        body.setObjectName("statKey")
        v.addWidget(body)
        if extra_lines:
            more = QLabel("\n".join(extra_lines))
            more.setWordWrap(True)
            more.setObjectName("statKey")
            v.addWidget(more)
        return box
