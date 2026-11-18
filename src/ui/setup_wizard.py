"""First-run setup wizard (machine settings + hardware overview)."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_meta import APP_NAME, APP_VERSION_LABEL, load_app_logo_pixmap
from monitor.hardware_report import build_hardware_report
from ui.busy_indicator import BusyIndicator
from ui.machine_settings import MachineSettingsForm, default_wizard_cfg


class _HwWorker(QThread):
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            self.finished_ok.emit(build_hardware_report(include_vram=True))
        except Exception as exc:
            self.failed.emit(str(exc))


class SetupWizardPage(QWidget):
    """Full-window first-run wizard. Emits finished(cfg_updates) when done."""

    finished = pyqtSignal(dict)

    def __init__(self, cfg: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("root")
        self._cfg = default_wizard_cfg(cfg)
        self._worker: _HwWorker | None = None
        self._report = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        logo = QLabel()
        pix = load_app_logo_pixmap(400, 88)
        if not pix.isNull():
            logo.setPixmap(pix)
        else:
            logo.setText(APP_NAME)
            logo.setFont(QFont("Bahnschrift", 22, QFont.Weight.Bold))
        root.addWidget(logo)
        ver = QLabel(f"{APP_VERSION_LABEL} — first-time setup")
        ver.setObjectName("tagline")
        root.addWidget(ver)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        # 0 Welcome
        w0 = QWidget()
        l0 = QVBoxLayout(w0)
        t0 = QLabel("Welcome")
        t0.setObjectName("sectionTitle")
        l0.addWidget(t0)
        b0 = QLabel(
            "This short wizard configures shared machine settings used by every "
            "network (BTC, BCH, XMR, RVN, ERG):\n\n"
            "• Temperature pause / resume (protects your hardware)\n"
            "• Mining intensity\n"
            "• CPU threads for Monero\n"
            "• GPU selection when you have more than one NVIDIA card\n\n"
            "Payout addresses stay on each network’s mining screen. "
            "You can change these later via Settings."
        )
        b0.setWordWrap(True)
        b0.setObjectName("tagline")
        l0.addWidget(b0)
        l0.addStretch(1)
        self._stack.addWidget(w0)

        # 1 Hardware
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        t1 = QLabel("Detected hardware")
        t1.setObjectName("sectionTitle")
        l1.addWidget(t1)
        self._busy = BusyIndicator()
        l1.addWidget(self._busy)
        self._hw_text = QTextEdit()
        self._hw_text.setReadOnly(True)
        self._hw_text.setMinimumHeight(180)
        l1.addWidget(self._hw_text, 1)
        hint = QLabel(
            "Support depends on drivers and free VRAM. "
            "BTC/BCH need OpenCL GPU; XMR uses CPU; RVN/ERG need NVIDIA CUDA + enough VRAM."
        )
        hint.setWordWrap(True)
        hint.setObjectName("tagline")
        l1.addWidget(hint)
        self._stack.addWidget(w1)

        # 2 Thermal + performance
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        t2 = QLabel("Temperature & performance")
        t2.setObjectName("sectionTitle")
        l2.addWidget(t2)
        tip = QLabel(
            "If you are unsure, keep the recommended values. "
            "Laptop GPUs overheat faster than desktop cards — lower Pause is safer."
        )
        tip.setWordWrap(True)
        tip.setObjectName("tagline")
        l2.addWidget(tip)
        self.form = MachineSettingsForm()
        self.form.load_from(self._cfg)  # fresh defaults: Pause 65°C / Resume 55°C
        btn_rec = QPushButton("Apply laptop recommendation (Pause 75°C / Resume 67°C)")
        btn_rec.clicked.connect(lambda: self.form.apply_recommended_thermal(laptop=True))
        btn_desk = QPushButton("Apply desktop recommendation (Pause 82°C / Resume 74°C)")
        btn_desk.clicked.connect(lambda: self.form.apply_recommended_thermal(laptop=False))
        l2.addWidget(btn_rec)
        l2.addWidget(btn_desk)
        l2.addWidget(self.form, 1)
        self._stack.addWidget(w2)

        # 3 Done
        w3 = QWidget()
        l3 = QVBoxLayout(w3)
        t3 = QLabel("Ready")
        t3.setObjectName("sectionTitle")
        l3.addWidget(t3)
        b3 = QLabel(
            "Settings are saved on this PC. Next you will pick a network and enter "
            "your payout address. Open Settings anytime from the menu to change "
            "intensity, temperatures, or GPU."
        )
        b3.setWordWrap(True)
        b3.setObjectName("tagline")
        l3.addWidget(b3)
        l3.addStretch(1)
        self._stack.addWidget(w3)

        nav = QHBoxLayout()
        self.btn_back = QPushButton("← Back")
        self.btn_back.clicked.connect(self._back)
        self.btn_next = QPushButton("Next →")
        self.btn_next.setObjectName("startBtn")
        self.btn_next.clicked.connect(self._next)
        nav.addWidget(self.btn_back)
        nav.addStretch(1)
        nav.addWidget(self.btn_next)
        root.addLayout(nav)

        self._stack.currentChanged.connect(self._on_page)
        self._on_page(0)

    def start_hardware_scan(self) -> None:
        self._busy.show_busy("Detecting CPU / GPU…")
        self._hw_text.setPlainText("Scanning…")
        self._worker = _HwWorker()
        self._worker.finished_ok.connect(self._on_hw)
        self._worker.failed.connect(self._on_hw_fail)
        self._worker.start()

    def _on_hw(self, report: object) -> None:
        self._busy.hide_busy()
        self._report = report
        lines: list[str] = []
        try:
            r = report
            lines.append(f"OpenCL GPU: {'OK' if getattr(r, 'opencl_ok', False) else 'No'} — {getattr(r, 'opencl_detail', '')}")
            lines.append(f"NVIDIA: {'OK' if getattr(r, 'nvidia_ok', False) else 'No'} — {getattr(r, 'nvidia_detail', '')}")
            for d in getattr(r, "opencl_devices", []) or []:
                lines.append(f"  • {getattr(d, 'name', d)} — {getattr(d, 'detail', '')}")
            cpu = getattr(r, "cpu_detail", None) or getattr(r, "cpu_name", "")
            if cpu:
                lines.append(f"CPU: {cpu}")
        except Exception as exc:
            lines.append(str(exc))
        text = "\n".join(lines) if lines else "No details."
        self._hw_text.setPlainText(text)
        self.form.set_hardware_summary(text.replace("\n", " | "))

    def _on_hw_fail(self, msg: str) -> None:
        self._busy.hide_busy()
        self._hw_text.setPlainText(f"Hardware scan failed: {msg}")

    def _on_page(self, idx: int) -> None:
        self.btn_back.setEnabled(idx > 0)
        self.btn_next.setText("Finish" if idx >= self._stack.count() - 1 else "Next →")
        if idx == 1 and self._report is None and self._worker is None:
            self.start_hardware_scan()

    def _back(self) -> None:
        i = self._stack.currentIndex()
        if i > 0:
            self._stack.setCurrentIndex(i - 1)

    def _next(self) -> None:
        i = self._stack.currentIndex()
        if i >= self._stack.count() - 1:
            updates = self.form.values()
            updates["setup_wizard_done"] = True
            self.finished.emit(updates)
            return
        if i == 2:
            # clamp resume < pause
            if self.form.resume_temp.value() >= self.form.pause_temp.value():
                self.form.resume_temp.setValue(max(40, self.form.pause_temp.value() - 5))
        self._stack.setCurrentIndex(i + 1)
