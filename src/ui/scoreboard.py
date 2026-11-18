"""LED digit scoreboard + tray overlay mini window."""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QObject, Qt, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mining.best_hash import format_diff_short
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
QLabel#diffSummary {
    color: #111111;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.5px;
}
QLabel#diffSummaryCompact {
    color: #ffffff;
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 0.5px;
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

_CELEBRATE_QSS = """
QFrame#casioBox {
    background: #06210f;
    border: 1px solid #00e676;
}
QLabel#diffSummary {
    color: #0a7a32;
}
QLabel#diffSummaryCompact {
    color: #00e676;
}
"""

_CELEBRATE_MS = 1600


def _summary_line(
    network_diff: float | None,
    gpu_best: float | None,
    accepted_best: float | None,
) -> str:
    return (
        f"NET {format_diff_short(network_diff)}  "
        f"GPU {format_diff_short(gpu_best)}  "
        f"ACC {format_diff_short(accepted_best)}"
    )


class ScoreboardWidget(QFrame):
    """Scoreboard: BLK / ACC / REJ / ATTEMPTS / TEMP (compact: attempts+temp on 2nd row)."""

    clicked = pyqtSignal()

    def __init__(self, *, compact: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("scoreboardRoot")
        self.setStyleSheet(_BOARD_QSS)
        self._compact = compact

        self.blk = CasioDigitRow("BLK", 3 if compact else 4, compact=compact)
        self.acc = CasioDigitRow("ACC", 4 if compact else 5, compact=compact)
        self.rej = CasioDigitRow("REJ", 4 if compact else 5, compact=compact)
        self.att = CasioDigitRow(
            "ATT" if compact else "ATTEMPTS",
            13 if compact else 17,
            compact=compact,
        )
        self.temp = CasioDigitRow("TEMP", 3, compact=compact)
        self.temp.set_text("--")

        # Main board owns the summary label (above ATTEMPTS). Compact hides it;
        # overlay title row shows the same text after "EBF".
        self.diff_summary = QLabel("")
        self.diff_summary.setObjectName("diffSummary")
        self.diff_summary.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.diff_summary.setVisible(False)
        self.diff_summary.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._celebrate_timer: QTimer | None = None
        self._summary_text = ""
        self._external_summary: QLabel | None = None

        if compact:
            self.diff_summary.hide()
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
            bottom = QHBoxLayout()
            bottom.setContentsMargins(0, 0, 0, 0)
            bottom.setSpacing(4)
            bottom.addWidget(self.att, 0)
            bottom.addWidget(self.temp, 0)
            bottom.addStretch(1)
            root.addLayout(bottom)
        else:
            # Bottom-align digit boxes so ATTEMPTS stays on the same row as
            # BLK/ACC/REJ/TEMP; NET/GPU/ACC label sits above the ATTEMPTS box only.
            outer = QHBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(6)
            bottom = Qt.AlignmentFlag.AlignBottom
            outer.addWidget(self.blk, 0, bottom)
            outer.addWidget(self.acc, 0, bottom)
            outer.addWidget(self.rej, 0, bottom)

            att_wrap = QWidget()
            att_wrap.setObjectName("attWrap")
            att_col = QVBoxLayout(att_wrap)
            att_col.setContentsMargins(0, 0, 0, 0)
            att_col.setSpacing(2)
            att_col.addWidget(
                self.diff_summary, 0, Qt.AlignmentFlag.AlignHCenter
            )
            att_col.addWidget(self.att, 0, Qt.AlignmentFlag.AlignHCenter)
            outer.addWidget(att_wrap, 0, bottom)

            outer.addWidget(self.temp, 0, bottom)
            outer.addStretch(1)

    def bind_external_summary(self, label: QLabel) -> None:
        """Mini overlay: show NET/GPU/ACC on the EBF title row."""
        self._external_summary = label

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

    def update_temp(self, temp_c: int | None) -> None:
        """Show probe °C on the rightmost row; '--' when missing/unreadable."""
        if temp_c is None:
            self.temp.set_text("--")
            return
        try:
            val = int(temp_c)
        except (TypeError, ValueError):
            self.temp.set_text("--")
            return
        if val < 0:
            self.temp.set_text("--")
            return
        self.temp.set_value(min(999, val))

    def set_difficulty_row(
        self,
        network_diff: float | None,
        best_diff: float | None,
        *,
        visible: bool,
        accepted_best: float | None = None,
    ) -> None:
        self._summary_text = _summary_line(network_diff, best_diff, accepted_best)
        if not visible:
            self._end_celebration()
        show = bool(visible)
        if self._compact:
            self.diff_summary.setVisible(False)
            if self._external_summary is not None:
                self._external_summary.setVisible(show)
                if show and self._celebrate_timer is None:
                    self._external_summary.setText(self._summary_text)
        else:
            self.diff_summary.setVisible(show)
            if show and self._celebrate_timer is None:
                self.diff_summary.setText(self._summary_text)

    def celebrate_record(self) -> None:
        """Flash green + NEW RECORD for ~1.6s."""
        target = self._active_summary_label()
        if target is None or not target.isVisible():
            return
        self.setStyleSheet(_BOARD_QSS + _CELEBRATE_QSS)
        target.setText(f"NEW RECORD  {self._summary_text}")
        if self._celebrate_timer is None:
            self._celebrate_timer = QTimer(self)
            self._celebrate_timer.setSingleShot(True)
            self._celebrate_timer.timeout.connect(self._end_celebration)
        self._celebrate_timer.start(_CELEBRATE_MS)

    def _active_summary_label(self) -> QLabel | None:
        if self._compact:
            return self._external_summary
        return self.diff_summary

    def _end_celebration(self) -> None:
        if self._celebrate_timer is not None:
            self._celebrate_timer.stop()
            self._celebrate_timer.deleteLater()
            self._celebrate_timer = None
        self.setStyleSheet(_BOARD_QSS)
        target = self._active_summary_label()
        if target is not None:
            target.setText(self._summary_text)

    def stop_alerts(self) -> None:
        if self._celebrate_timer is not None:
            self._end_celebration()
        for row in (self.blk, self.acc, self.rej, self.att, self.temp):
            row.stop_alerts()

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
        # Session-only: after the user drags, keep that spot until app restart.
        self._user_placed = False
        self._drag_offset: QPoint | None = None

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

        # Title bar only: drag here; never opens the main window.
        self.title_bar = QWidget()
        self.title_bar.setObjectName("overlayTitleBar")
        self.title_bar.setCursor(Qt.CursorShape.SizeAllCursor)
        top = QHBoxLayout(self.title_bar)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        tip = QLabel("EBF")
        tip.setObjectName("casioTitle")
        tip.setStyleSheet("font-size: 8px; font-weight: 700;")
        tip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top.addWidget(tip, 0)

        self.diff_title = QLabel("")
        self.diff_title.setObjectName("diffSummaryCompact")
        self.diff_title.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self.diff_title.setVisible(False)
        self.diff_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top.addWidget(self.diff_title, 1)

        btn = QPushButton("×")
        btn.setObjectName("scoreClose")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("Hide scoreboard (tray menu → Show scoreboard)")
        btn.clicked.connect(self._user_close)
        top.addWidget(btn, 0)
        shell_l.addWidget(self.title_bar)

        self.board = ScoreboardWidget(compact=True)
        self.board.bind_external_summary(self.diff_title)
        self.board.clicked.connect(self.activated.emit)
        shell_l.addWidget(self.board)
        lay.addWidget(shell)
        self.adjustSize()
        self.title_bar.installEventFilter(self)

    def _after_content_resize(self) -> None:
        self.adjustSize()
        if self.isVisible() and not self._user_placed:
            self.place_bottom_right()

    def update_counts(
        self,
        blocks: int,
        accepted: int,
        rejected: int,
        attempts: int,
    ) -> None:
        self.board.update_counts(blocks, accepted, rejected, attempts)
        self._after_content_resize()

    def update_temp(self, temp_c: int | None) -> None:
        self.board.update_temp(temp_c)
        self._after_content_resize()

    def set_difficulty_row(
        self,
        network_diff: float | None,
        best_diff: float | None,
        *,
        visible: bool,
        accepted_best: float | None = None,
    ) -> None:
        self.board.set_difficulty_row(
            network_diff,
            best_diff,
            visible=visible,
            accepted_best=accepted_best,
        )
        self._after_content_resize()

    def celebrate_record(self) -> None:
        self.board.celebrate_record()

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
        # Fresh process → _user_placed is False → tray-top default.
        # Same session after a manual drag → keep the user's spot.
        if not self._user_placed:
            self.place_bottom_right()
        self.show()
        self.raise_()

    def stop_alerts(self) -> None:
        self.board.stop_alerts()

    def _user_close(self) -> None:
        self._closing_by_user = True
        self.board.stop_alerts()
        self.hide()
        if self._on_user_close:
            self._on_user_close()
        self._closing_by_user = False

    def closeEvent(self, event) -> None:  # noqa: N802
        self.board.stop_alerts()
        app = QApplication.instance()
        if app is not None and app.closingDown():
            self._on_user_close = None
            event.accept()
            return
        if (
            self._on_user_close
            and not self._closing_by_user
            and self.isVisible()
        ):
            cb = self._on_user_close
            self._on_user_close = None
            cb()
        event.accept()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        # Drag only from the thin title bar (EBF + records). Never open main window.
        if obj is self.title_bar and isinstance(event, QMouseEvent):
            et = event.type()
            if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                self.title_bar.grabMouse()
                return True
            if (
                et == QEvent.Type.MouseMove
                and self._drag_offset is not None
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                self._user_placed = True
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
            if et == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = None
                self.title_bar.releaseMouse()
                return True
        return super().eventFilter(obj, event)
