"""Manual donate: pick network → QR + address + copy. Does not affect mining."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPixmap, QTextOption
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app_meta import APP_NAME, load_app_icon, load_app_logo_pixmap
from donate_addresses import DONATE_OPTIONS, DonateOption, get_donate_option


def qr_pixmap(payload: str, *, modules: int = 7) -> QPixmap:
    """Build QR matrix → QPixmap (no Pillow required)."""
    import qrcode

    qr = qrcode.QRCode(version=None, box_size=1, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    scale = max(4, int(modules))
    img = QImage(n * scale, n * scale, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    dark = QColor("#0b3d2e")
    for y, row in enumerate(matrix):
        for x, cell in enumerate(row):
            if not cell:
                continue
            for dy in range(scale):
                for dx in range(scale):
                    img.setPixelColor(x * scale + dx, y * scale + dy, dark)
    return QPixmap.fromImage(img)


class DonateDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Donate — {APP_NAME}")
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.setMinimumWidth(480)
        self.setMinimumHeight(520)
        self._opt: DonateOption | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        head_logo = QLabel()
        head_pix = load_app_logo_pixmap(360, 72)
        if not head_pix.isNull():
            head_logo.setPixmap(head_pix)
            head_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(head_logo)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # Page 0: pick network
        p0 = QWidget()
        l0 = QVBoxLayout(p0)
        l0.setSpacing(10)
        title = QLabel("Choose a donation network")
        title.setObjectName("sectionTitle")
        title.setFont(QFont("Bahnschrift", 16, QFont.Weight.Bold))
        l0.addWidget(title)
        hint = QLabel(
            "Optional manual donation. This does not affect mining speed, your wallet, "
            "or the pool session — copy and send only if you want to support the project."
        )
        hint.setWordWrap(True)
        hint.setObjectName("tagline")
        l0.addWidget(hint)
        for opt in DONATE_OPTIONS:
            btn = QPushButton(f"{opt.label}\n{opt.network_note}")
            btn.setMinimumHeight(52)
            btn.setStyleSheet("text-align: left; padding: 8px 12px;")
            btn.clicked.connect(lambda _=False, oid=opt.id: self._show_option(oid))
            l0.addWidget(btn)
        l0.addStretch(1)
        close0 = QPushButton("Close")
        close0.clicked.connect(self.reject)
        l0.addWidget(close0)
        self.stack.addWidget(p0)

        # Page 1: thanks + QR
        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        l1.setSpacing(10)
        self.lbl_thanks = QLabel("Thank you")
        self.lbl_thanks.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_thanks.setFont(QFont("Bahnschrift", 22, QFont.Weight.Bold))
        self.lbl_thanks.setStyleSheet("color: #0b3d2e;")
        l1.addWidget(self.lbl_thanks)
        self.lbl_thanks_sub = QLabel(
            f"Thank you for supporting {APP_NAME}.\n"
            "Every contribution helps keep development going."
        )
        self.lbl_thanks_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_thanks_sub.setWordWrap(True)
        self.lbl_thanks_sub.setObjectName("tagline")
        l1.addWidget(self.lbl_thanks_sub)

        self.lbl_net = QLabel("")
        self.lbl_net.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_net.setFont(QFont("Bahnschrift", 13, QFont.Weight.DemiBold))
        l1.addWidget(self.lbl_net)

        self.lbl_qr = QLabel()
        self.lbl_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_qr.setMinimumHeight(220)
        l1.addWidget(self.lbl_qr)

        addr_row = QHBoxLayout()
        addr_row.setSpacing(8)
        self.lbl_addr = QPlainTextEdit()
        self.lbl_addr.setReadOnly(True)
        self.lbl_addr.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.lbl_addr.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.lbl_addr.setFont(QFont("Cascadia Mono", 10))
        self.lbl_addr.setFixedHeight(72)
        self.lbl_addr.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.lbl_addr.setStyleSheet(
            "QPlainTextEdit { background: #f4f7f5; border: 1px solid #c5d0cb; "
            "border-radius: 6px; padding: 6px; }"
        )
        addr_row.addWidget(self.lbl_addr, 1)
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setFixedWidth(100)
        self.btn_copy.setMinimumHeight(40)
        self.btn_copy.clicked.connect(self._copy_addr)
        addr_row.addWidget(self.btn_copy, 0, Qt.AlignmentFlag.AlignTop)
        l1.addLayout(addr_row)

        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setObjectName("tagline")
        self.lbl_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l1.addWidget(self.lbl_note)

        nav = QHBoxLayout()
        back = QPushButton("← Network list")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        nav.addWidget(back)
        nav.addStretch(1)
        done = QPushButton("Close")
        done.clicked.connect(self.accept)
        nav.addWidget(done)
        l1.addLayout(nav)
        self.stack.addWidget(p1)

    def _show_option(self, option_id: str) -> None:
        opt = get_donate_option(option_id)
        if opt is None:
            return
        self._opt = opt
        self.lbl_net.setText(opt.label)
        self.lbl_note.setText(opt.network_note)
        self.lbl_addr.setPlainText(opt.address)
        try:
            self.lbl_qr.setPixmap(qr_pixmap(opt.qr_payload, modules=8))
        except Exception as exc:
            self.lbl_qr.setText(f"Could not build QR: {exc}")
        self.stack.setCurrentIndex(1)

    def _copy_addr(self) -> None:
        if self._opt is None:
            return
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._opt.address)
        self.btn_copy.setText("Copied")
        QMessageBox.information(
            self,
            "Copied",
            f"{self._opt.label} address copied to the clipboard.\nThank you!",
        )
