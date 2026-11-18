"""Casio-style scoreboard + tray overlay mini window."""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.casio_digits import CasioDigitRow

_BOARD_QSS = """
QFrame#scoreboardRoot {
    background: transparent;
    border: none;
}
QFrame#casioBox {
    background: #0a0a0a;
    border: 1px solid #333;
    border-radius: 6px;
}
QLabel#casioTitle {
    color: #ff6b5a;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1px;
}
QPushButton#scoreClose {
    background: #1a1a1a;
    color: #ff6b5a;
    border: 1px solid #333;
    border-radius: 3px;
    font-weight: 700;
    padding: 0;
    min-width: 16px;
    max-width: 16px;
    min-height: 16px;
    max-height: 16px;
    font-size: 10px;
}
QPushButton#scoreClose:hover {
    background: #d32f2f;
    color: #ffffff;
    border-color: #d32f2f;
}
QFrame#overlayShell {
    background: #111;
    border: 1px solid #333;
    border-radius: 8px;
}
"""


class ScoreboardWidget(QFrame):
    """Scoreboard: BLK / ACC / REJ + ATTEMPTS (compact overlay: attempts on 2nd row)."""

    clicked = pyqtSignal()

    def __init__(self, *, compact: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("scoreboardRoot")
        self.setStyleSheet(_BOARD_QSS)
        self._compact = compact

        self.blk = CasioDigitRow("BLK", 3 if compact else 4, compact=compact)
        self.acc = CasioDigitRow("ACC", 4 if compact else 5, compact=compact)
        self.rej = CasioDigitRow("REJ", 4 if compact else 5, compact=compact)
        # ATTEMPTS: wide zero pad for strong GPUs; grows further if needed (full integer)
        self.att = CasioDigitRow(
            "ATT" if compact else "ATTEMPTS",
            12 if compact else 14,
            compact=compact,
        )

        if compact:
            # Mini overlay: top = BLK/ACC/REJ, bottom = full ATTEMPTS row
            root = QVBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(4)
            top = QHBoxLayout()
            top.setContentsMargins(0, 0, 0, 0)
            top.setSpacing(4)
            top.addWidget(self.blk)
            top.addWidget(self.acc)
            top.addWidget(self.rej)
            root.addLayout(top)
            root.addWidget(self.att)
        else:
            root = QHBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(6)
            root.addWidget(self.blk)
            root.addWidget(self.acc)
            root.addWidget(self.rej)
            root.addWidget(self.att, 1)

    def update_counts(
        self,
        blocks: int,
        accepted: int,
        rejected: int,
        attempts: int,
    ) -> None:
        blocks = max(0, int(blocks))
        self.blk.set_value(blocks)
        self.blk.set_alert(blocks != 0)
        self.acc.set_value(accepted)
        self.rej.set_value(rejected)
        self.att.set_value(max(0, int(attempts)), full=True)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ScoreboardOverlayWindow(QWidget):
    """Bottom-right always-on-top mini scoreboard while main window is in the tray."""

    activated = pyqtSignal()

    def __init__(
        self,
        *,
        on_user_close: Optional[Callable[[], None]] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_user_close = on_user_close
        self._closing_by_user = False
        self._drag_pos: QPoint | None = None

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(_BOARD_QSS)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        shell = QFrame()
        shell.setObjectName("overlayShell")
        shell_l = QVBoxLayout(shell)
        shell_l.setContentsMargins(5, 3, 5, 5)
        shell_l.setSpacing(3)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(2)
        tip = QLabel("EBF")
        tip.setObjectName("casioTitle")
        tip.setStyleSheet("font-size: 8px; font-weight: 700;")
        top.addWidget(tip, 1)
        btn = QPushButton("×")
        btn.setObjectName("scoreClose")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("Hide scoreboard (tray menu → Show scoreboard)")
        btn.clicked.connect(self._user_close)
        top.addWidget(btn, 0)
        shell_l.addLayout(top)

        self.board = ScoreboardWidget(compact=True)
        self.board.clicked.connect(self.activated.emit)
        shell_l.addWidget(self.board)
        lay.addWidget(shell)
        self.adjustSize()

    def update_counts(
        self,
        blocks: int,
        accepted: int,
        rejected: int,
        attempts: int,
    ) -> None:
        self.board.update_counts(blocks, accepted, rejected, attempts)
        self.adjustSize()
        if self.isVisible():
            self.place_bottom_right()

    def place_bottom_right(self, margin: int = 12) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.adjustSize()
        x = geo.right() - self.width() - margin + 1
        y = geo.bottom() - self.height() - margin + 1
        self.move(max(geo.left() + margin, x), max(geo.top() + margin, y))

    def show_overlay(self) -> None:
        self.place_bottom_right()
        self.show()
        self.raise_()

    def _user_close(self) -> None:
        self._closing_by_user = True
        self.hide()
        if self._on_user_close:
            self._on_user_close()
        self._closing_by_user = False

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._on_user_close and not self._closing_by_user:
            self._on_user_close()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)
