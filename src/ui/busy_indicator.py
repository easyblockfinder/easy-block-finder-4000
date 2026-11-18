"""Circular loading spinner + message — visible wait state for long UI ops."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


class _CircleSpinner(QWidget):
    """Animated circular arc (not a thin progress bar)."""

    def __init__(self, parent: QWidget | None = None, *, size: int = 36) -> None:
        super().__init__(parent)
        self._angle = 0
        self._size = size
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._angle = (self._angle + 12) % 360
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        margin = 3
        rect = QRectF(margin, margin, self._size - 2 * margin, self._size - 2 * margin)

        track = QPen(QColor("#d0d7de"), 3.5)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(track)
        p.drawEllipse(rect)

        arc = QPen(QColor("#0d9488"), 3.5)
        arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(arc)
        # Qt angles: 1/16 degree; 0 = 3 o'clock, positive = counter-clockwise
        start = int((-self._angle) * 16)
        span = int(-270 * 16)
        p.drawArc(rect, start, span)
        p.end()


class BusyIndicator(QWidget):
    """Full-width busy strip with circle spinner so waiting is obvious."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("busyIndicator")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(14)
        self._spinner = _CircleSpinner(size=40)
        row.addWidget(self._spinner, 0, Qt.AlignmentFlag.AlignVCenter)

        self._lbl = QLabel("Working…")
        self._lbl.setWordWrap(True)
        self._lbl.setStyleSheet(
            "font-weight: 700; font-size: 14px; color: #0f766e;"
        )
        row.addWidget(self._lbl, 1)
        root.addLayout(row)

        self._sub = QLabel("Please wait — do not click repeatedly.")
        self._sub.setWordWrap(True)
        self._sub.setStyleSheet("color: #64748b; font-size: 12px;")
        root.addWidget(self._sub)

        self.setStyleSheet(
            "#busyIndicator {"
            "  background: #ecfdf5;"
            "  border: 1px solid #99f6e4;"
            "  border-radius: 8px;"
            "}"
        )
        self.setVisible(False)

    def show_busy(self, message: str = "Please wait…") -> None:
        self._lbl.setText(message or "Please wait…")
        self.setVisible(True)
        self._spinner.start()
        self.raise_()

    def hide_busy(self) -> None:
        self._spinner.stop()
        self.setVisible(False)

    # Aliases used by setup wizard / older call sites
    def start(self, message: str = "Please wait…") -> None:
        self.show_busy(message)

    def stop(self) -> None:
        self.hide_busy()
