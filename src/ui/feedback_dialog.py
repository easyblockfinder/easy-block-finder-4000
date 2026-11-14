"""Feedback / suggestions — copy email + open popular webmail compose."""

from __future__ import annotations

from urllib.parse import quote

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app_meta import APP_NAME, APP_VERSION_LABEL, load_app_icon

FEEDBACK_EMAIL = "sametkuzu82@gmail.com"

# (label, compose URL template with {email} {subject} {body})
_WEBMAIL = (
    (
        "Gmail",
        "https://mail.google.com/mail/?view=cm&fs=1&to={email}&su={subject}&body={body}",
    ),
    (
        "Outlook / Hotmail",
        "https://outlook.live.com/mail/0/deeplink/compose?to={email}&subject={subject}&body={body}",
    ),
    (
        "Yahoo Mail",
        "https://compose.mail.yahoo.com/?to={email}&subject={subject}&body={body}",
    ),
)


class FeedbackDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Feedback — {APP_NAME}")
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        title = QLabel("Feedback, ideas & suggestions")
        title.setFont(QFont("Bahnschrift", 14, QFont.Weight.Bold))
        root.addWidget(title)

        hint = QLabel(
            "Share bug reports, feature ideas, hardware notes, or any other feedback. "
            "Copy the address, or open your webmail with the address already filled in."
        )
        hint.setWordWrap(True)
        hint.setObjectName("tagline")
        root.addWidget(hint)

        row = QHBoxLayout()
        self.email_edit = QLineEdit(FEEDBACK_EMAIL)
        self.email_edit.setReadOnly(True)
        self.email_edit.setFont(QFont("Cascadia Mono", 11))
        self.email_edit.setMinimumHeight(36)
        row.addWidget(self.email_edit, 1)
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setMinimumHeight(36)
        self.btn_copy.setFixedWidth(100)
        self.btn_copy.clicked.connect(self._copy_email)
        row.addWidget(self.btn_copy)
        root.addLayout(row)

        services = QLabel("Open in webmail (email is also copied to the clipboard):")
        services.setWordWrap(True)
        root.addWidget(services)

        btn_row = QHBoxLayout()
        for label, _tmpl in _WEBMAIL:
            b = QPushButton(label)
            b.setMinimumHeight(36)
            b.clicked.connect(lambda _=False, name=label: self._open_webmail(name))
            btn_row.addWidget(b)
        root.addLayout(btn_row)

        mailto = QPushButton("Default mail app (mailto:)")
        mailto.setMinimumHeight(34)
        mailto.clicked.connect(self._open_mailto)
        root.addWidget(mailto)

        note = QLabel(
            f"Please include your {APP_VERSION_LABEL} build and OS/GPU details when reporting issues."
        )
        note.setWordWrap(True)
        note.setObjectName("tagline")
        root.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        root.addWidget(buttons)

    def _subject_body(self) -> tuple[str, str]:
        subject = f"{APP_NAME} feedback ({APP_VERSION_LABEL})"
        body = (
            f"Hello,\n\n"
            f"App: {APP_NAME} {APP_VERSION_LABEL}\n"
            f"Feedback:\n\n"
        )
        return subject, body

    def _copy_email(self, *, silent: bool = False) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(FEEDBACK_EMAIL)
        self.btn_copy.setText("Copied")
        if not silent:
            QMessageBox.information(
                self,
                "Copied",
                f"{FEEDBACK_EMAIL}\ncopied to the clipboard.",
            )

    def _open_webmail(self, name: str) -> None:
        self._copy_email(silent=True)
        subject, body = self._subject_body()
        tmpl = next(t for label, t in _WEBMAIL if label == name)
        url = tmpl.format(
            email=quote(FEEDBACK_EMAIL, safe="@"),
            subject=quote(subject),
            body=quote(body),
        )
        QDesktopServices.openUrl(QUrl(url))

    def _open_mailto(self) -> None:
        self._copy_email(silent=True)
        subject, body = self._subject_body()
        url = (
            f"mailto:{FEEDBACK_EMAIL}"
            f"?subject={quote(subject)}&body={quote(body)}"
        )
        QDesktopServices.openUrl(QUrl(url))
