"""Help → About EBF4000."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app_meta import (
    APP_DEVELOPER,
    APP_DEVELOPER_EMAIL,
    APP_LICENSE,
    APP_NAME,
    APP_SHORT,
    APP_VERSION_LABEL,
    GITHUB_URL,
    load_app_icon,
    load_app_logo_pixmap,
)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_SHORT}")
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)

        logo = QLabel()
        pix = load_app_logo_pixmap(360, 64)
        if not pix.isNull():
            logo.setPixmap(pix)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(logo)

        title = QLabel(APP_NAME)
        title.setFont(QFont("Bahnschrift", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        ver = QLabel(APP_VERSION_LABEL)
        ver.setObjectName("tagline")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(ver)

        body = QLabel(
            f"<p><b>License:</b> {APP_LICENSE}</p>"
            f"<p><b>Developer:</b> {APP_DEVELOPER}<br>"
            f"<a href=\"mailto:{APP_DEVELOPER_EMAIL}\">{APP_DEVELOPER_EMAIL}</a></p>"
            f"<p><b>Source:</b> <a href=\"{GITHUB_URL}\">{GITHUB_URL}</a></p>"
            "<p>Open-source solo / pool mining helper. "
            "This app does not redirect your hashrate — use Donate if you want "
            "to support development.</p>"
        )
        body.setWordWrap(True)
        body.setOpenExternalLinks(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(body)

        row = QHBoxLayout()
        btn_gh = QPushButton("GitHub Repository")
        btn_gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        row.addWidget(btn_gh)
        btn_donate = QPushButton("Donate…")
        btn_donate.clicked.connect(self._donate)
        row.addWidget(btn_donate)
        root.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        root.addWidget(buttons)

    def _donate(self) -> None:
        from ui.donate_dialog import DonateDialog

        DonateDialog(self).exec()
