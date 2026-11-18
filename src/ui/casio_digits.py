"""Casio-style 7-segment digit widgets (each digit in its own cell)."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPolygonF
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

# Standard 7-seg map: a b c d e f g
_SEGMENTS = {
    "0": "abcdef",
    "1": "bc",
    "2": "abdeg",
    "3": "abcdg",
    "4": "bcfg",
    "5": "acdfg",
    "6": "acdefg",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
    "-": "g",
    " ": "",
}


class SevenSegmentDigit(QWidget):
    def __init__(
        self,
        *,
        on_color: str = "#ff2a1f",
        off_color: str = "#4a1818",
        bg: str = "#2a2a2a",
        cell_w: int = 22,
        cell_h: int = 36,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ch = "0"
        self._on = QColor(on_color)
        self._off = QColor(off_color)
        self._bg = QColor(bg)
        self._cell_w = max(8, int(cell_w))
        self._cell_h = max(14, int(cell_h))
        self.setFixedSize(self._cell_w, self._cell_h)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._cell_w, self._cell_h)

    def set_char(self, ch: str) -> None:
        c = (ch or " ")[0]
        if c not in _SEGMENTS:
            c = " "
        if c != self._ch:
            self._ch = c
            self.update()

    def set_bg(self, color: str) -> None:
        bg = QColor(color)
        if bg != self._bg:
            self._bg = bg
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # LCD cell floor (gray normally; green when BLK alert blinks)
        p.fillRect(self.rect(), self._bg)
        w, h = float(self.width()), float(self.height())
        m = max(1.5, min(w, h) * 0.10)
        t = max(2.0, min(w, h) * 0.145)
        gap = max(0.8, t * 0.22)
        active = set(_SEGMENTS.get(self._ch, ""))

        # Inner drawing area — leave gaps so "0" reads as segments, not a letter O
        left = m
        right = w - m
        top = m
        bot = h - m
        mid_y = (top + bot) / 2.0
        span_h = right - left

        def horiz(y_center: float) -> QPolygonF:
            y0 = y_center - t / 2.0
            x0 = left + gap
            x1 = right - gap
            n = t * 0.42
            return QPolygonF(
                [
                    QPointF(x0 + n, y0),
                    QPointF(x1 - n, y0),
                    QPointF(x1, y0 + t / 2.0),
                    QPointF(x1 - n, y0 + t),
                    QPointF(x0 + n, y0 + t),
                    QPointF(x0, y0 + t / 2.0),
                ]
            )

        def vert(x_center: float, y0: float, y1: float) -> QPolygonF:
            x0 = x_center - t / 2.0
            n = t * 0.42
            yy0 = y0 + gap
            yy1 = y1 - gap
            return QPolygonF(
                [
                    QPointF(x0 + t / 2.0, yy0),
                    QPointF(x0 + t, yy0 + n),
                    QPointF(x0 + t, yy1 - n),
                    QPointF(x0 + t / 2.0, yy1),
                    QPointF(x0, yy1 - n),
                    QPointF(x0, yy0 + n),
                ]
            )

        segs = {
            "a": horiz(top + t / 2.0),
            "b": vert(right - t / 2.0, top + t * 0.55, mid_y - t * 0.15),
            "c": vert(right - t / 2.0, mid_y + t * 0.15, bot - t * 0.55),
            "d": horiz(bot - t / 2.0),
            "e": vert(left + t / 2.0, mid_y + t * 0.15, bot - t * 0.55),
            "f": vert(left + t / 2.0, top + t * 0.55, mid_y - t * 0.15),
            "g": horiz(mid_y),
        }
        p.setPen(Qt.PenStyle.NoPen)
        for name, poly in segs.items():
            p.setBrush(self._on if name in active else self._off)
            p.drawPolygon(poly)


class CasioDigitRow(QFrame):
    """One metric box: title + N separate Casio digit cells."""

    def __init__(
        self,
        title: str,
        width: int,
        *,
        compact: bool = False,
        on_color: str = "#ff2a1f",
        off_color: str = "#4a1818",
        digit_bg: str = "#2a2a2a",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("casioBox")
        # Hug digit content — never expand and space digits apart on wide layouts
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._compact = compact
        self._on_color = on_color
        self._off_color = off_color
        self._digit_bg = digit_bg
        self._width = max(1, int(width))
        self._cell_w = 16 if compact else 22
        self._cell_h = 26 if compact else 36
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4 if compact else 8, 3 if compact else 4, 4 if compact else 8, 3 if compact else 4)
        lay.setSpacing(2 if compact else 2)
        lay.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._title = QLabel(title)
        self._title.setObjectName("casioTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if compact:
            self._title.setStyleSheet("font-size: 8px; letter-spacing: 0.5px;")
        lay.addWidget(self._title)
        self._digit_row = QHBoxLayout()
        self._digit_row.setSpacing(2 if compact else 3)
        self._digit_row.setContentsMargins(0, 0, 0, 0)
        self._digit_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._digits: list[SevenSegmentDigit] = []
        for _ in range(self._width):
            self._digit_row.addWidget(self._make_digit())
        lay.addLayout(self._digit_row)

        self._alert = False
        self._alert_phase = False
        self._alert_timer = QTimer(self)
        self._alert_timer.setInterval(450)
        self._alert_timer.timeout.connect(self._on_alert_tick)
        self._apply_box_chrome(False)

    def _make_digit(self) -> SevenSegmentDigit:
        d = SevenSegmentDigit(
            on_color=self._on_color,
            off_color=self._off_color,
            bg=self._digit_bg,
            cell_w=self._cell_w,
            cell_h=self._cell_h,
        )
        self._digits.append(d)
        return d

    def ensure_width(self, width: int) -> None:
        """Grow digit cells so the full value fits (never truncates)."""
        need = max(1, int(width))
        while len(self._digits) < need:
            self._digit_row.addWidget(self._make_digit())
            # New cells inherit current alert floor color
            if self._alert and self._alert_phase:
                self._digits[-1].set_bg("#1b5e20")
        self._width = max(self._width, need)

    def stop_alerts(self) -> None:
        """Stop blink timer before widget teardown (avoids native abort on quit)."""
        self._alert = False
        self._alert_phase = False
        self._alert_timer.stop()

    def set_alert(self, active: bool) -> None:
        """Green blinking digit background while value is non-zero (block found)."""
        active = bool(active)
        if active == self._alert:
            return
        self._alert = active
        self._alert_phase = False
        if active:
            self._alert_timer.start()
            self._on_alert_tick()
        else:
            self._alert_timer.stop()
            self._apply_box_chrome(False)

    def _on_alert_tick(self) -> None:
        self._alert_phase = not self._alert_phase
        self._apply_box_chrome(self._alert_phase)

    def _apply_box_chrome(self, lit: bool) -> None:
        if self._alert and lit:
            self.setStyleSheet(
                "QFrame#casioBox {"
                " background: #0f3d1a; border: 1px solid #22c55e; border-radius: 6px;"
                "}"
                "QLabel#casioTitle { color: #86efac; font-weight: 700; }"
            )
            cell = "#1b5e20"
        else:
            # Clear inline override so shared board QSS applies when idle
            self.setStyleSheet("")
            cell = self._digit_bg
            if self._alert:
                # Dim phase still green-tinted so it reads as alert, not normal
                self.setStyleSheet(
                    "QFrame#casioBox {"
                    " background: #0a1a10; border: 1px solid #166534; border-radius: 6px;"
                    "}"
                    "QLabel#casioTitle { color: #4ade80; font-weight: 700; }"
                )
                cell = "#143d22"
        for dig in self._digits:
            dig.set_bg(cell)

    def set_value(self, value: int | str, *, full: bool = False) -> None:
        if isinstance(value, int):
            text = str(max(0, value))
        else:
            text = str(value)
        if full:
            self.ensure_width(len(text))
            if len(text) < self._width:
                text = text.zfill(self._width)
        else:
            if len(text) < self._width:
                text = text.zfill(self._width)
            elif len(text) > self._width:
                text = text[-self._width :]
        for i, dig in enumerate(self._digits):
            dig.set_char(text[i] if i < len(text) else " ")

    def set_text(self, text: str) -> None:
        """Raw character display (right-aligned, space-padded; supports '-' blanks)."""
        raw = str(text or "")
        if len(raw) > self._width:
            raw = raw[-self._width :]
        raw = raw.rjust(self._width)
        for i, dig in enumerate(self._digits):
            dig.set_char(raw[i] if i < len(raw) else " ")
