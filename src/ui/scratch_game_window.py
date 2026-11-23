"""Scratch Mining board — canvas virtualized TILE_GRID² tiles; reveal after GPU result."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from game.mega_map import (
    board_grid_side,
    en2_tile_to_world_xy,
    state_key,
    world_size_tiles,
    world_xy_to_en2_tile,
)
from game.pan_fold import fold_pan_y_into_bias
from game.tile_space import TILE_COUNT, TILE_GRID
from mining.best_hash import format_diff_short

_STATS_QSS = """
QFrame#gameStatsBand {
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 12px;
}
QFrame#gameMetricCard {
    background: #111827;
    border: 1px solid #334155;
    border-radius: 10px;
}
QFrame#gameMetricCard[flash="true"] {
    background: #1e3a5f;
    border: 1px solid #38bdf8;
}
QLabel#gameMetricKey {
    color: #94a3b8;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
}
QLabel#gameMetricVal {
    color: #f1f5f9;
    font-size: 14px;
    font-weight: 800;
    font-family: "Cascadia Mono", "Consolas", monospace;
}
QFrame#gameMetricCard[kind="context"] {
    background: #0c1524;
    border: 1px solid #3b4f6b;
}
QFrame#gameMetricCard[kind="context"] QLabel#gameMetricVal {
    font-size: 13px;
    font-weight: 700;
    line-height: 1.25;
}
QLabel#gameEventBanner {
    color: #e2e8f0;
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 10px 12px;
    font-weight: 700;
    font-size: 13px;
}
QLabel#gameEventBanner[kind="new_job"] {
    color: #e0f2fe;
    background: #0c4a6e;
    border: 1px solid #38bdf8;
}
QLabel#gameEventBanner[kind="new_block"] {
    color: #fef3c7;
    background: #78350f;
    border: 1px solid #f59e0b;
}
QLabel#gameEventBanner[kind="board"] {
    color: #dbeafe;
    background: #1e3a5f;
    border: 1px solid #60a5fa;
}
QLabel#gameFlashTitle {
    color: #f8fafc;
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 0.4px;
    padding: 2px 0 0 0;
}
QPushButton#depthNavBtn {
    background: #111827;
    border: 1px solid #334155;
    border-radius: 8px;
    color: #e2e8f0;
    font-size: 11px;
    font-weight: 700;
    padding: 8px 4px;
}
QPushButton#depthNavBtn:hover {
    background: #1e293b;
    border: 1px solid #38bdf8;
    color: #f8fafc;
}
QPushButton#depthNavBtn:pressed {
    background: #0c4a6e;
}
QPushButton#depthNavBtn:disabled {
    background: #0b1220;
    border: 1px solid #1e293b;
    color: #475569;
}
"""


class GameMetricCard(QFrame):
    """Key/value tile — compact metric or wider context card."""

    def __init__(
        self,
        key: str,
        parent: QWidget | None = None,
        *,
        kind: str = "metric",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("gameMetricCard")
        self.setProperty("kind", kind)
        context = kind == "context"
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred if context else QSizePolicy.Policy.Fixed,
        )
        self.setMinimumHeight(78 if context else 52)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)
        self.lbl_key = QLabel(key.upper())
        self.lbl_key.setObjectName("gameMetricKey")
        self.lbl_val = QLabel("—")
        self.lbl_val.setObjectName("gameMetricVal")
        self.lbl_val.setWordWrap(True)
        self.lbl_val.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        lay.addWidget(self.lbl_key)
        lay.addWidget(self.lbl_val, 1 if context else 0)

    def set_value(self, text: str) -> None:
        self.lbl_val.setText(text or "—")


class GameStatsBand(QFrame):
    """Two rows: context + hashes/shares on top; remaining metrics on one row below."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("gameStatsBand")
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(8)

        flash_box = QFrame()
        flash_lay = QVBoxLayout(flash_box)
        flash_lay.setContentsMargins(0, 0, 0, 0)
        flash_lay.setSpacing(4)
        self.lbl_flash_title = QLabel("")
        self.lbl_flash_title.setObjectName("gameFlashTitle")
        self.lbl_flash_title.setVisible(False)
        flash_lay.addWidget(self.lbl_flash_title)
        self.lbl_event = QLabel("")
        self.lbl_event.setObjectName("gameEventBanner")
        self.lbl_event.setWordWrap(True)
        self.lbl_event.setVisible(False)
        flash_lay.addWidget(self.lbl_event)
        outer.addWidget(flash_box)

        self.card_job = GameMetricCard("Active Job", kind="context")
        self.card_board = GameMetricCard("Map", kind="context")
        self.card_tiles = GameMetricCard("Tiles Revealed", kind="context")
        self.card_hashes = GameMetricCard("Hash Attempts", kind="context")
        self.card_shares = GameMetricCard("Shares", kind="context")
        self.card_network = GameMetricCard("Network")
        self.card_temp = GameMetricCard("Temperature")
        self.card_gpu = GameMetricCard("GPU Best")
        self.card_rate = GameMetricCard("Eff. Hashrate")
        self.card_acc = GameMetricCard("ACC Best")
        self.card_hash_time = GameMetricCard("Hashing Time")
        self.card_session = GameMetricCard("Session Best")

        # Row 1: status cards + Hash Attempts / Shares (Tiles slightly narrower).
        row1_cards = (
            self.card_job,
            self.card_board,
            self.card_tiles,
            self.card_hashes,
            self.card_shares,
        )
        # Row 2: every remaining metric on a single line.
        row2_cards = (
            self.card_network,
            self.card_temp,
            self.card_gpu,
            self.card_rate,
            self.card_acc,
            self.card_hash_time,
            self.card_session,
        )

        self._cards_wrap = QWidget()
        wrap_lay = QVBoxLayout(self._cards_wrap)
        wrap_lay.setContentsMargins(0, 0, 0, 0)
        wrap_lay.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(self.card_job, 3)
        row1.addWidget(self.card_board, 3)
        row1.addWidget(self.card_tiles, 2)
        row1.addWidget(self.card_hashes, 2)
        row1.addWidget(self.card_shares, 2)
        wrap_lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        for card in row2_cards:
            row2.addWidget(card, 1)
        wrap_lay.addLayout(row2)

        outer.addWidget(self._cards_wrap)

        cards = row1_cards + row2_cards
        self._opacity = QGraphicsOpacityEffect(self._cards_wrap)
        self._opacity.setOpacity(1.0)
        self._cards_wrap.setGraphicsEffect(self._opacity)
        self._anim: QPropertyAnimation | None = None
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._end_flash)
        self._cards = cards

    def set_event(self, kind: str, text: str, *, title: str = "") -> None:
        if not text and not title:
            self.lbl_event.setVisible(False)
            self.lbl_event.setText("")
            self.lbl_flash_title.setVisible(False)
            self.lbl_flash_title.setText("")
            self.lbl_event.setProperty("kind", "")
            self.lbl_event.style().unpolish(self.lbl_event)
            self.lbl_event.style().polish(self.lbl_event)
            return
        if title:
            self.lbl_flash_title.setText(title)
            self.lbl_flash_title.setVisible(True)
        else:
            self.lbl_flash_title.setVisible(bool(self.lbl_flash_title.text()))
        self.lbl_event.setText(text or "")
        self.lbl_event.setProperty("kind", kind or "")
        self.lbl_event.style().unpolish(self.lbl_event)
        self.lbl_event.style().polish(self.lbl_event)
        self.lbl_event.setVisible(bool(text))

    def play_new_work_animation(
        self, *, kind: str = "new_job", message: str = "", title: str = ""
    ) -> None:
        """Pulse metric cards; keep a clear text banner readable during the flash."""
        for card in self._cards:
            card.setProperty("flash", True)
            card.style().unpolish(card)
            card.style().polish(card)
        if kind == "new_block":
            default_title = "New Bitcoin Block Detected"
            default_msg = (
                "Another block has been detected on the network. "
                "Tiles reset — preparing the next mining round."
            )
        elif kind == "new_job":
            default_title = "New Mining Job Received"
            default_msg = (
                "The pool has updated your mining work. "
                "Tiles reset for the new job."
            )
        else:
            default_title = "Search Space Extended"
            default_msg = "Continuing on the next nonce region of the same map."
        self.set_event(
            kind if kind in ("new_job", "new_block") else "board",
            message or default_msg,
            title=title or default_title,
        )
        if self._anim is not None:
            self._anim.stop()
        self._opacity.setOpacity(0.35)
        anim = QPropertyAnimation(self._opacity, b"opacity", self)
        anim.setDuration(520)
        anim.setStartValue(0.35)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._anim = anim
        self._flash_timer.start(1200)

    def _end_flash(self) -> None:
        for card in self._cards:
            card.setProperty("flash", False)
            card.style().unpolish(card)
            card.style().polish(card)

def _diff_color(diff: float | None) -> QColor:
    if diff is None:
        return QColor("#334155")
    if diff >= 1e12:
        return QColor("#f59e0b")
    if diff >= 1e9:
        return QColor("#22c55e")
    if diff >= 1e6:
        return QColor("#38bdf8")
    if diff >= 1e3:
        return QColor("#818cf8")
    return QColor("#64748b")


# Fixed tile size (px). Zoom is locked — cell size must never depend on viewport.
_TARGET_CELL_PX = 32.0
_FIXED_CELL_PX = _TARGET_CELL_PX
# Safe center = viewport inset by this many px. Outside it → auto-pan that way.
_EDGE_MARGIN_PX = 100.0
_PAN_SPEED = 30.0
# Scratch: hard camera velocity from cursor offset to viewport center (timer-driven).
_SCRATCH_PAN_SPEED = 96.0
_SCRATCH_DEADZONE = 0.14


_USER_PICKAXE_NAME = "user_pickaxe.png"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _black_matte_to_transparent(img: QImage) -> QImage:
    """Remove solid black (or near-black) studio backdrop."""
    out = img.convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(out.height()):
        for x in range(out.width()):
            c = out.pixelColor(x, y)
            # Pure / near-black background
            if c.red() < 28 and c.green() < 28 and c.blue() < 28:
                c.setAlpha(0)
                out.setPixelColor(x, y, c)
            # Soften fringing on dark edges
            elif c.red() < 45 and c.green() < 45 and c.blue() < 45 and c.alpha() > 0:
                c.setAlpha(max(0, int(c.alpha() * (c.lightness() / 45.0))))
                out.setPixelColor(x, y, c)
    return out


def _crop_to_alpha(img: QImage, pad: int = 2) -> QImage:
    """Tight crop around opaque pixels."""
    min_x, min_y = img.width(), img.height()
    max_x, max_y = -1, -1
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() < 16:
                continue
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if max_x < 0:
        return img
    min_x = max(0, min_x - pad)
    min_y = max(0, min_y - pad)
    max_x = min(img.width() - 1, max_x + pad)
    max_y = min(img.height() - 1, max_y + pad)
    return img.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


def _find_tip_hotspot(img: QImage) -> tuple[int, int]:
    """Hotspot ≈ furthest tip of the metal head (top-left on user art)."""
    best = None
    best_score = None
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() < 40:
                continue
            # Prefer upper-left opaque pixels (long pick tip on supplied art).
            score = x + y
            if best_score is None or score < best_score:
                best_score = score
                best = (x, y)
    if best is None:
        return max(1, img.width() // 8), max(1, img.height() // 8)
    return best


def build_dig_cursor() -> QCursor:
    """Use the user-supplied pickaxe image as the board dig pointer."""
    size = 40
    path = _project_root() / "assets" / "cursors" / _USER_PICKAXE_NAME
    raw = QImage(str(path)) if path.is_file() else QImage()
    if raw.isNull():
        # Absolute fallback: tiny geometric mark so we never crash.
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        return QCursor(pm, 1, 1)

    keyed = _black_matte_to_transparent(raw)
    cropped = _crop_to_alpha(keyed, pad=4)
    tip_x, tip_y = _find_tip_hotspot(cropped)
    scaled = cropped.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    # Scale hotspot with the image.
    sx = scaled.width() / max(1, cropped.width())
    sy = scaled.height() / max(1, cropped.height())
    hx = int(tip_x * sx)
    hy = int(tip_y * sy)

    canvas = QPixmap(scaled.width(), scaled.height())
    canvas.fill(Qt.GlobalColor.transparent)
    qp = QPainter(canvas)
    qp.drawImage(0, 0, scaled)
    qp.end()

    return QCursor(canvas, hx, hy)


class DepthMeter(QWidget):
    """Left-side depth gauge for the vertical EN2 shaft."""

    def __init__(
        self, canvas: "ScratchBoardCanvas", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self.setFixedWidth(72)
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self.setMinimumHeight(120)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#0b1220"))
        info = self._canvas.depth_readout()
        w = float(self.width())
        h = float(self.height())
        margin_t = 28.0
        margin_b = 18.0
        track_x = w * 0.55
        track_top = margin_t
        track_bot = h - margin_b
        track_h = max(1.0, track_bot - track_top)

        # Title
        p.setPen(QColor("#94a3b8"))
        p.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        p.drawText(
            QRectF(2, 2, w - 4, 14),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            "DEPTH",
        )

        # Track
        p.setPen(QPen(QColor("#334155"), 1.0))
        p.drawLine(QPointF(track_x, track_top), QPointF(track_x, track_bot))

        top_en2 = int(info["top_en2"])
        bot_en2 = int(info["bottom_en2"])
        cur_en2 = int(info["en2"])
        local_row = int(info["local_row"])
        # Never tick across the whole 2^32 shaft — viewport-local only.
        if bot_en2 - top_en2 > 64:
            top_en2 = max(0, cur_en2 - 8)
            bot_en2 = cur_en2 + 8
        span = max(1, bot_en2 - top_en2)

        # Tick marks for EN2 boards visible in the viewport span.
        tick_step = 1
        if span > 12:
            tick_step = max(1, span // 8)
        p.setFont(QFont("Cascadia Mono", 7))
        for en2 in range(top_en2, bot_en2 + 1, tick_step):
            t = (en2 - top_en2) / span
            y = track_top + t * track_h
            p.setPen(QPen(QColor("#475569"), 1.0))
            p.drawLine(QPointF(track_x - 6, y), QPointF(track_x + 6, y))
            p.setPen(QColor("#64748b"))
            p.drawText(
                QRectF(2, y - 8, track_x - 10, 16),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                str(en2),
            )

        # Current depth marker (viewport center).
        cur = cur_en2 + (local_row / max(1, TILE_GRID))
        t = (cur - top_en2) / span
        t = min(1.0, max(0.0, t))
        y = track_top + t * track_h
        tri = QPainterPath()
        tri.moveTo(track_x + 8, y)
        tri.lineTo(track_x + 18, y - 6)
        tri.lineTo(track_x + 18, y + 6)
        tri.closeSubpath()
        p.fillPath(tri, QColor("#38bdf8"))
        p.setPen(QPen(QColor("#7dd3fc"), 1.0))
        p.drawLine(QPointF(track_x - 8, y), QPointF(track_x + 8, y))

        # Readout under the track
        p.setPen(QColor("#e2e8f0"))
        p.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        p.drawText(
            QRectF(2, track_bot + 1, w - 4, 14),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            f"EN2 {cur_en2}",
        )


class ScratchBoardCanvas(QWidget):
    """Virtual EN2×TILE_GRID² mega-map; only the viewport is drawn."""

    cell_clicked = pyqtSignal(int, int)  # extranonce2, tile_id
    view_changed = pyqtSignal()  # pan/zoom — depth meter refresh

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        # Fresh cursor each canvas (asset v8 / emoji / geometry — no stale cache).
        self._dig_cursor = build_dig_cursor()
        # Cursor is set on enter/leave — default arrow until pointer is on the board.
        self.unsetCursor()
        self.setMinimumSize(480, 480)
        self._en2_size = 4
        self._live_en2 = 0
        self._states: dict[int, str] = {}
        self._best: dict[int, float | None] = {}
        self._detail: dict[int, dict] = {}
        # Zoom locked — kept at 1.0 for compat; cell size is always _FIXED_CELL_PX.
        self._scale = 1.0
        # Screen pos of world tile (0, _y_bias). Y bias keeps float pan float-safe
        # deep in the 2^32 shaft (absolute wy*cs would freeze pan / blank the board).
        self._pan = QPointF(0, 0)
        self._y_bias = 0
        self._drag_origin: QPointF | None = None
        self._pan_origin = QPointF(0, 0)
        self._y_bias_origin = 0
        self._hover = -1
        self._mining_ids: set[int] = set()
        self._scratching = False
        self._last_scratch_key = -1
        self._cursor_pos = QPointF(0, 0)
        self._scratch_last_pos: QPointF | None = None
        self._zoom_ready = False
        self._edge_timer = QTimer(self)
        self._edge_timer.setInterval(16)
        self._edge_timer.timeout.connect(self._center_auto_pan)

    def set_map_params(self, *, extranonce2_size: int, live_en2: int) -> None:
        en2_size = max(1, int(extranonce2_size or 4))
        live = int(live_en2)
        changed = en2_size != self._en2_size
        self._en2_size = en2_size
        self._live_en2 = live
        if changed or not self._zoom_ready:
            self._zoom_to_readable(reset_pan=True)

    def set_tile(
        self,
        tile_id: int,
        *,
        state: str,
        best_difficulty: float | None = None,
        detail: dict | None = None,
        extranonce2: int | None = None,
    ) -> None:
        en2 = self._live_en2 if extranonce2 is None else int(extranonce2)
        key = state_key(en2, int(tile_id))
        self._states[key] = state
        if best_difficulty is not None or state == "COMPLETED":
            self._best[key] = best_difficulty
        if detail:
            self._detail[key] = dict(detail)
        if state == "MINING":
            self._mining_ids.add(key)
        else:
            self._mining_ids.discard(key)
        self.update()

    def reset_board(self, *, reset_pan: bool = False) -> None:
        """Clear painted tiles. Pan stays put unless reset_pan is requested."""
        self._states.clear()
        self._best.clear()
        self._detail.clear()
        self._mining_ids.clear()
        if reset_pan:
            self._zoom_to_readable(reset_pan=True)
        self.update()

    def _cancel_scratch_input(self) -> None:
        """Stop edge-pan / mouse-grab so jumps cannot start a mega scratch line."""
        self._scratching = False
        self._scratch_last_pos = None
        self._last_scratch_key = -1
        self._edge_timer.stop()
        if self.mouseGrabber() is self:
            self.releaseMouse()

    def jump_to_tile(
        self, en2: int, tile_id: int, *, align: str = "top"
    ) -> None:
        """Pan so (en2, tile) is near the top or bottom of the viewport."""
        self._cancel_scratch_input()
        if not self._zoom_ready:
            self._zoom_to_readable(reset_pan=False)
        cs = self._cell_size()
        wx, wy = en2_tile_to_world_xy(
            int(en2), int(tile_id), extranonce2_size=self._en2_size
        )
        # Keep relative Y near zero so float pan stays precise.
        if align == "bottom":
            self._y_bias = max(0, int(wy) - TILE_GRID + 1)
            rel_y = int(wy) - self._y_bias
            self._pan = QPointF(
                16.0 - float(wx) * cs,
                float(self.height()) - 24.0 - (rel_y + 1) * cs,
            )
        else:
            self._y_bias = max(0, int(wy) - 2)
            rel_y = int(wy) - self._y_bias
            self._pan = QPointF(16.0 - float(wx) * cs, 16.0 - rel_y * cs)
        self._clamp_pan()
        self.view_changed.emit()
        self.update()

    def has_inflight_paint(self) -> bool:
        """True while UI still shows queued/mining tiles (may lag controller)."""
        if self._mining_ids:
            return True
        for st in self._states.values():
            if st in ("QUEUED", "MINING"):
                return True
        return False

    def clear_stale_inflight_paint(self) -> None:
        """When GPU queue is idle, convert leftover QUEUED/MINING paint → INTERRUPTED."""
        changed = False
        for key, st in list(self._states.items()):
            if st in ("QUEUED", "MINING"):
                self._states[key] = "INTERRUPTED"
                self._mining_ids.discard(key)
                changed = True
        if changed:
            self.update()

    def jump_to_surface(self) -> None:
        """Shaft start — EN2 0 / tile 0."""
        self.jump_to_tile(0, 0, align="top")

    def _world_size(self) -> tuple[int, int]:
        return world_size_tiles(self._en2_size)

    def _cell_size(self) -> float:
        """Constant tile width/height — zoom locked."""
        return float(_FIXED_CELL_PX)

    def _origin(self) -> QPointF:
        """Screen position of world tile (0, _y_bias)."""
        return QPointF(self._pan.x(), self._pan.y())

    def _set_view_on_world(self, wx: int, wy: int, screen: QPointF) -> None:
        """Place world (wx,wy) under screen point (float-safe via y bias)."""
        cs = self._cell_size()
        self._y_bias = max(0, int(wy) - TILE_GRID * 2)
        rel_y = int(wy) - self._y_bias
        self._pan = QPointF(
            screen.x() - int(wx) * cs,
            screen.y() - rel_y * cs,
        )

    def _zoom_to_readable(self, *, reset_pan: bool = False) -> None:
        """Init / re-anchor view. Scale stays locked; cell size is fixed."""
        self._scale = 1.0
        if reset_pan or not self._zoom_ready:
            wx, wy = en2_tile_to_world_xy(
                self._live_en2, 0, extranonce2_size=self._en2_size
            )
            self._set_view_on_world(wx, wy, QPointF(16.0, 16.0))
        self._zoom_ready = True
        self._clamp_pan()
        self._rebase_camera()
        self.view_changed.emit()

    def _fold_pan_into_bias(self) -> None:
        """Keep pan.y in a small float band by absorbing tiles into _y_bias.

        World Y under a screen point: wy = y_bias + (sy - pan.y) / cs.
        Deep scroll makes pan.y very negative → raise y_bias and add k*cs to pan.
        Shallow scroll makes pan.y very positive → lower y_bias and subtract k*cs.
        (Previously both bias updates were inverted, so after ~limit px of descent
        every pan tick was undone and the camera froze with the cursor at the bottom.)
        """
        cs = self._cell_size()
        if cs <= 0:
            return
        limit = max(1500.0, float(self.height()) * 3.0)
        pan_y, bias = fold_pan_y_into_bias(
            float(self._pan.y()), int(self._y_bias), cs, limit
        )
        self._y_bias = int(bias)
        self._pan = QPointF(self._pan.x(), pan_y)

    def _clamp_pan(self) -> None:
        cs = self._cell_size()
        world_w, world_h = self._world_size()
        margin = cs
        self._fold_pan_into_bias()
        bias = int(self._y_bias)
        min_ox = self.width() - margin - world_w * cs
        max_ox = margin
        ox = min(max(self._pan.x(), min_ox), max_ox)

        # Clamp using integer world rows — never bias*cs as a float bound.
        top_wy = bias + int(math.floor((-self._pan.y()) / cs))
        vis = int(math.ceil(float(self.height()) / cs)) + 2
        oy = self._pan.y()
        if top_wy < 0:
            oy = oy + top_wy * cs  # top_wy negative → push content down
            top_wy = 0
        if top_wy + vis > world_h:
            overflow = top_wy + vis - world_h
            oy = oy + overflow * cs
        self._pan = QPointF(ox, oy)
        self._fold_pan_into_bias()
        # Keep bias inside the shaft.
        max_bias = max(0, world_h - 1)
        if self._y_bias < 0:
            self._pan = QPointF(
                self._pan.x(), self._pan.y() - self._y_bias * cs
            )
            self._y_bias = 0
        elif self._y_bias > max_bias:
            extra = int(self._y_bias) - max_bias
            self._pan = QPointF(self._pan.x(), self._pan.y() + extra * cs)
            self._y_bias = max_bias

    def _rebase_camera(self) -> None:
        """Re-center bias around the viewport without huge float deltas."""
        cs = self._cell_size()
        if cs <= 0:
            return
        _, world_h = self._world_size()
        mid_wy = int(self._y_bias) + int(
            math.floor((float(self.height()) * 0.5 - self._pan.y()) / cs)
        )
        target_rel = TILE_GRID * 2
        new_bias = max(0, min(max(0, world_h - 1), mid_wy - target_rel))
        if abs(new_bias - int(self._y_bias)) < TILE_GRID:
            self._fold_pan_into_bias()
            return
        rel_mid = mid_wy - new_bias
        self._y_bias = int(new_bias)
        self._pan = QPointF(
            self._pan.x(),
            float(self.height()) * 0.5 - rel_mid * cs,
        )
        self._clamp_pan()

    def _world_xy_at(self, pos: QPointF) -> tuple[int, int]:
        origin = self._origin()
        cs = self._cell_size()
        wx = int(math.floor((pos.x() - origin.x()) / cs))
        rel_y = int(math.floor((pos.y() - origin.y()) / cs))
        return wx, int(self._y_bias) + rel_y

    def _cell_at(self, pos: QPointF) -> tuple[int, int] | None:
        wx, wy = self._world_xy_at(pos)
        return world_xy_to_en2_tile(wx, wy, extranonce2_size=self._en2_size)

    def depth_readout(self) -> dict[str, int]:
        """Viewport depth for the left meter (EN2 shaft position)."""
        w = max(1.0, float(self.width()))
        h = max(1.0, float(self.height()))
        mid = self._cell_at(QPointF(w * 0.5, h * 0.5))
        top = self._cell_at(QPointF(w * 0.5, 4.0))
        bot = self._cell_at(QPointF(w * 0.5, h - 4.0))
        en2 = int(mid[0]) if mid else int(self._live_en2)
        local_row = 0
        if mid is not None:
            local_row = int(mid[1]) // TILE_GRID
        top_en2 = int(top[0]) if top else en2
        bot_en2 = int(bot[0]) if bot else en2
        if bot_en2 < top_en2:
            top_en2, bot_en2 = bot_en2, top_en2
        # Ensure the scale has at least one board of span for ticks.
        if bot_en2 == top_en2:
            bot_en2 = top_en2 + 1
        return {
            "en2": en2,
            "local_row": local_row,
            "top_en2": top_en2,
            "bottom_en2": bot_en2,
        }

    def _scratch_world_line(self, ax: int, ay: int, bx: int, by: int) -> None:
        """Scratch every world cell on the segment (ax,ay)→(bx,by)."""
        dx = abs(bx - ax)
        dy = abs(by - ay)
        # Hard cap — a Top/Bottom jump must never enqueue millions of cells.
        if max(dx, dy) > 96:
            bx, by = ax, ay
            dx = dy = 0
        sx = 1 if ax < bx else -1
        sy = 1 if ay < by else -1
        err = dx - dy
        x, y = ax, ay
        for _ in range(max(dx, dy) + 1):
            cell = world_xy_to_en2_tile(x, y, extranonce2_size=self._en2_size)
            self._try_scratch_cell(cell)
            if x == bx and y == by:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    def _scratch_line(self, a: QPointF, b: QPointF) -> None:
        """Scratch every world cell under screen segment a→b (same pan)."""
        ax, ay = self._world_xy_at(a)
        bx, by = self._world_xy_at(b)
        self._scratch_world_line(ax, ay, bx, by)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._zoom_ready and self.width() > 40 and self.height() > 40:
            self._zoom_to_readable(reset_pan=True)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # First show only — later job changes must not yank the camera up.
        QTimer.singleShot(
            0, lambda: self._zoom_to_readable(reset_pan=not self._zoom_ready)
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        # Pickaxe only while the pointer is over the board canvas.
        if self._drag_origin is None:
            self.setCursor(self._dig_cursor)
        if not self._edge_timer.isActive():
            self._edge_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover >= 0:
            self._hover = -1
            self.update()
        # Outside the board (stats / depth rail / chrome) → normal arrow.
        if not self._scratching and self._drag_origin is None:
            self.unsetCursor()
            self._edge_timer.stop()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(self.rect(), QColor("#0b1220"))
        origin = self._origin()
        cs = self._cell_size()
        world_w, world_h = self._world_size()
        bias = int(self._y_bias)
        gap = max(1.0, min(2.5, cs * 0.08))
        border_w = max(1.0, min(2.0, cs * 0.06))
        left = max(0, int(math.floor((-origin.x()) / cs)) - 1)
        right = min(world_w, int(math.floor((self.width() - origin.x()) / cs)) + 2)
        rel_top = int(math.floor((-origin.y()) / cs)) - 1
        rel_bot = int(math.floor((self.height() - origin.y()) / cs)) + 2
        # Guard against corrupt pan producing astronomical ranges.
        max_span = int(math.ceil(float(self.height()) / max(1.0, cs))) + 8
        if rel_bot - rel_top > max_span or rel_bot - rel_top < 0:
            rel_top = -2
            rel_bot = max_span
        # Cap draw budget if zoomed way out (skip cells; never stretch rects).
        if (right - left) * max(1, rel_bot - rel_top) > 12_000:
            step = max(
                1,
                int(((right - left) * max(1, rel_bot - rel_top) / 12_000) ** 0.5),
            )
        else:
            step = 1
        font = QFont("Cascadia Mono", max(7, int(cs * 0.28)))
        p.setFont(font)
        for rel_y in range(rel_top, rel_bot, step):
            wy = bias + rel_y
            if wy < 0 or wy >= world_h:
                continue
            for wx in range(left, right, step):
                decoded = world_xy_to_en2_tile(
                    wx, wy, extranonce2_size=self._en2_size
                )
                if decoded is None:
                    continue
                en2, tid = decoded
                key = state_key(en2, tid)
                rect = QRectF(
                    origin.x() + wx * cs + gap * 0.5,
                    origin.y() + rel_y * cs + gap * 0.5,
                    max(1.0, cs - gap),
                    max(1.0, cs - gap),
                )
                state = self._states.get(key, "UNOPENED")
                best = self._best.get(key)
                hovered = key == self._hover
                # Subtle board boundary tint
                if (wx % TILE_GRID == 0 or wy % TILE_GRID == 0) and cs >= 10:
                    board_edge = True
                else:
                    board_edge = False
                if state == "COMPLETED":
                    fill = _diff_color(best)
                    border = QColor("#94a3b8")
                elif state == "MINING":
                    fill = QColor("#1d4ed8")
                    border = QColor("#93c5fd")
                elif state == "QUEUED":
                    fill = QColor("#1e3a5f")
                    border = QColor("#60a5fa")
                elif state == "INTERRUPTED":
                    fill = QColor("#7c2d12")
                    border = QColor("#fdba74")
                elif state == "INVALIDATED":
                    fill = QColor("#1f2937")
                    border = QColor("#4b5563")
                else:
                    # Alternate EN2 islands slightly so the mega-map reads.
                    fill = (
                        QColor("#1e293b")
                        if (int(en2) & 1) == 0
                        else QColor("#172033")
                    )
                    border = QColor("#334155") if board_edge else QColor("#475569")
                if hovered:
                    fill = QColor(fill).lighter(145)
                    border = (
                        QColor("#f8fafc")
                        if state in ("UNOPENED", "INTERRUPTED")
                        else QColor(border).lighter(140)
                    )
                p.fillRect(rect, fill)
                if cs >= 6:
                    p.setPen(QPen(border, border_w))
                    p.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
                if hovered and state in ("UNOPENED", "INTERRUPTED") and cs >= 10:
                    p.setPen(QPen(QColor("#38bdf8"), 1))
                    inset = min(3.0, cs * 0.12)
                    p.drawRect(rect.adjusted(inset, inset, -inset, -inset))
                if step == 1 and state == "COMPLETED" and cs >= 18:
                    p.setPen(QColor("#f8fafc"))
                    p.drawText(
                        rect,
                        int(Qt.AlignmentFlag.AlignCenter),
                        format_diff_short(best),
                    )
                elif step == 1 and state == "MINING" and cs >= 16:
                    p.setPen(QColor("#e2e8f0"))
                    p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "…")
                elif step == 1 and state == "UNOPENED" and cs >= 22:
                    p.setPen(QColor("#64748b"))
                    p.drawText(
                        rect, int(Qt.AlignmentFlag.AlignCenter), str(tid)
                    )

    def _try_scratch_cell(self, cell: tuple[int, int] | None) -> None:
        if cell is None:
            return
        en2, tid = cell
        key = state_key(en2, tid)
        if key == self._last_scratch_key:
            return
        st = self._states.get(key, "UNOPENED")
        # Only skip terminal / in-flight paints — never leave a false QUEUED stuck.
        if st in ("COMPLETED", "MINING", "INVALIDATED"):
            self._last_scratch_key = key
            return
        if st == "QUEUED":
            # Already accepted into the real queue — don't re-spam.
            self._last_scratch_key = key
            return
        self._last_scratch_key = key
        self.cell_clicked.emit(en2, tid)

    def _edge_margin(self) -> float:
        """Safe center inset (px). Outside → auto-pan toward that edge (hover)."""
        side = min(max(1.0, float(self.width())), max(1.0, float(self.height())))
        return min(_EDGE_MARGIN_PX, side * 0.28)

    def _clamp_screen_pos(self, pos: QPointF) -> QPointF:
        """Keep scratch / dig samples inside the widget (grabMouse outside OK)."""
        w = max(1.0, float(self.width()))
        h = max(1.0, float(self.height()))
        return QPointF(
            min(max(pos.x(), 0.0), w - 1.0),
            min(max(pos.y(), 0.0), h - 1.0),
        )

    def _hover_edge_pan_delta(self, pos: QPointF) -> tuple[float, float]:
        """Hover-only edge band pan (not used while scratching)."""
        w = max(1.0, float(self.width()))
        h = max(1.0, float(self.height()))
        m = self._edge_margin()
        x = pos.x()
        y = pos.y()
        dx = 0.0
        dy = 0.0

        def _ramp(t: float) -> float:
            t = min(1.0, max(0.0, t))
            return _PAN_SPEED * (0.55 + 1.45 * t * t)

        if x < m:
            dx = _ramp(1.0 - max(0.0, x) / m)
        elif x > w - m:
            dx = -_ramp((x - (w - m)) / m)
        if y < m:
            dy = _ramp(1.0 - max(0.0, y) / m)
        elif y > h - m:
            dy = -_ramp((y - (h - m)) / m)
        return dx, dy

    def _scratch_follow_pan_delta(self, pos: QPointF) -> tuple[float, float]:
        """Hard camera velocity from cursor offset to center. Works at edges without leaving window."""
        w = max(1.0, float(self.width()))
        h = max(1.0, float(self.height()))
        # Normalized offset from center; |n|>1 when pointer is outside the widget.
        nx = (pos.x() - w * 0.5) / max(1.0, w * 0.5)
        ny = (pos.y() - h * 0.5) / max(1.0, h * 0.5)
        dead = _SCRATCH_DEADZONE

        def _axis(n: float) -> float:
            if abs(n) <= dead:
                return 0.0
            sign = 1.0 if n > 0.0 else -1.0
            # Remap dead→0 … 1→1, allow outside boost up to ~1.6
            t = (abs(n) - dead) / max(1e-6, 1.0 - dead)
            t = min(1.6, t)
            # Quadratic ease-in for hard feel near edges
            return sign * (t * t)

        # Mouse right of center → look right → pan.x decreases
        return -_axis(nx) * _SCRATCH_PAN_SPEED, -_axis(ny) * _SCRATCH_PAN_SPEED

    def _apply_pan_delta(self, dx: float, dy: float, *, scratch: bool) -> None:
        if dx == 0.0 and dy == 0.0:
            return
        pos = self._cursor_pos
        scratch_pos = self._clamp_screen_pos(pos)
        wx0, wy0 = self._world_xy_at(scratch_pos)
        self._pan = QPointF(self._pan.x() + dx, self._pan.y() + dy)
        self._clamp_pan()
        self._rebase_camera()
        if scratch:
            wx1, wy1 = self._world_xy_at(scratch_pos)
            self._scratch_world_line(wx0, wy0, wx1, wy1)
        cell = self._cell_at(scratch_pos)
        if cell is not None:
            self._hover = state_key(cell[0], cell[1])
        self.view_changed.emit()
        self.update()

    def _center_auto_pan(self) -> None:
        """Timer pan: scratch = center-offset follow; idle = edge band."""
        if self._drag_origin is not None:
            return
        if self._scratching:
            dx, dy = self._scratch_follow_pan_delta(self._cursor_pos)
            self._apply_pan_delta(dx, dy, scratch=True)
            return
        if not self.underMouse():
            self._edge_timer.stop()
            return
        dx, dy = self._hover_edge_pan_delta(self._cursor_pos)
        self._apply_pan_delta(dx, dy, scratch=False)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = QPointF(event.position())
        self._cursor_pos = pos
        if not self._edge_timer.isActive() and self._drag_origin is None:
            self._edge_timer.start()
        if self._drag_origin is not None:
            # Ctrl/middle pan stays grab-sense (drag map with hand).
            delta = event.position() - self._drag_origin
            self._y_bias = int(self._y_bias_origin)
            self._pan = self._pan_origin + delta
            self._clamp_pan()
            self._rebase_camera()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.view_changed.emit()
            self.update()
            return
        if self._scratching and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            # Dig along path only — camera is timer-driven from cursor vs center.
            prev = self._scratch_last_pos or pos
            self._scratch_line(
                self._clamp_screen_pos(prev),
                self._clamp_screen_pos(pos),
            )
            self._scratch_last_pos = QPointF(pos)
            if not self._edge_timer.isActive():
                self._edge_timer.start()
        cell = self._cell_at(self._clamp_screen_pos(pos) if self._scratching else pos)
        key = state_key(cell[0], cell[1]) if cell else -1
        if self._drag_origin is None:
            self.setCursor(self._dig_cursor)
        if key != self._hover:
            self._hover = key
            self.update()
        if cell is not None and not self._scratching:
            d = self._detail.get(key) or {}
            state = self._states.get(key, "UNOPENED")
            tip = (
                f"EN2 {cell[0]} · Tile {cell[1]} · {state}\n"
                f"Best {format_diff_short(self._best.get(key))}\n"
                f"Hashes {d.get('hashes', '—')} · "
                f"Shares {d.get('share_candidates', '—')}\n"
                f"ACC {d.get('accepted', 0)} / REJ {d.get('rejected', 0)}"
            )
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._cursor_pos = QPointF(event.position())
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._drag_origin = event.position()
            self._pan_origin = QPointF(self._pan)
            self._y_bias_origin = int(self._y_bias)
            self._scratching = False
            self._scratch_last_pos = None
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._scratching = True
            self._last_scratch_key = -1
            self._scratch_last_pos = QPointF(event.position())
            self._try_scratch_cell(self._cell_at(event.position()))
            self.setCursor(self._dig_cursor)
            self.grabMouse()
            if not self._edge_timer.isActive():
                self._edge_timer.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._scratching = False
            self._last_scratch_key = -1
            self._scratch_last_pos = None
            self._edge_timer.stop()
            if self.mouseGrabber() is self:
                self.releaseMouse()
            if self.rect().contains(event.position().toPoint()):
                self.setCursor(self._dig_cursor)
            else:
                self.unsetCursor()
        if event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
        ):
            self._drag_origin = None
            if self.rect().contains(event.position().toPoint()):
                self.setCursor(self._dig_cursor)
            else:
                self.unsetCursor()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        # Zoom locked — fixed tile size; ignore wheel.
        event.accept()


class ScratchGameWindow(QMainWindow):
    closed = pyqtSignal()

    def __init__(
        self,
        *,
        on_tile: Callable[[int, int], bool],
        on_reload_tiles: Callable[[], list] | None = None,
        parent: QWidget | None = None,
        **_ignored,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scratch Mining — Easy Block Finder 4000")
        self.resize(980, 760)
        self.setStyleSheet(_STATS_QSS)
        self._on_tile = on_tile
        self._on_reload_tiles = on_reload_tiles
        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        self.lbl_banner = QLabel(
            f"Full extranonce2 space as a vertical shaft of {TILE_GRID}×{TILE_GRID} "
            f"islands ({TILE_COUNT} tiles × ~4.19M hashes each). "
            "Left/right stays inside the current EN2; dig down for the next board. "
            "Hold-and-drag to scratch (camera follows). Tile size fixed · Ctrl/middle-drag pans. "
            "Accepted shares are not Bitcoin block rewards."
        )
        self.lbl_banner.setWordWrap(True)
        self.lbl_banner.setStyleSheet("color:#94a3b8; font-size:12px;")
        lay.addWidget(self.lbl_banner)

        self.stats_band = GameStatsBand()
        lay.addWidget(self.stats_band, 0)

        # Back-compat aliases used by main_window tile-queue feedback
        self.lbl_event = self.stats_band.lbl_event

        board_row = QWidget()
        board_lay = QHBoxLayout(board_row)
        board_lay.setContentsMargins(0, 0, 0, 0)
        board_lay.setSpacing(8)
        self.canvas = ScratchBoardCanvas()
        self.canvas.cell_clicked.connect(self._clicked)
        self.depth_meter = DepthMeter(self.canvas)
        self.canvas.view_changed.connect(self.depth_meter.update)

        rail = QWidget()
        rail.setFixedWidth(72)
        rail_lay = QVBoxLayout(rail)
        rail_lay.setContentsMargins(0, 0, 0, 0)
        rail_lay.setSpacing(6)
        self.btn_jump_top = QPushButton("▲ Top")
        self.btn_jump_top.setObjectName("depthNavBtn")
        self.btn_jump_top.setToolTip("Jump to shaft start (EN2 0)")
        self.btn_jump_top.clicked.connect(self.canvas.jump_to_surface)
        rail_lay.addWidget(self.btn_jump_top, 0)
        rail_lay.addWidget(self.depth_meter, 1)
        self._sync_depth_nav(busy=False)

        board_lay.addWidget(rail, 0)
        board_lay.addWidget(self.canvas, 1)
        lay.addWidget(board_row, 1)

        self._session_best: float | None = None
        self._last_game_event = ""
        self._active_board_id = ""
        self._nav_busy = False
        self._pulse = QTimer(self)
        self._pulse.timeout.connect(self._tick_board)
        self._pulse.start(400)

    def _tick_board(self) -> None:
        self.canvas.update()
        self.depth_meter.update()
        # Do not re-derive busy from paint alone — that kept buttons stuck disabled.
        self._sync_depth_nav(busy=self._nav_busy)

    def _sync_depth_nav(self, busy: bool | None = None) -> None:
        """Disable Top while controller still has hash work."""
        if busy is None:
            busy = self._nav_busy
        self._nav_busy = bool(busy)
        tip_busy = "Disabled while tiles are hashing / queued"
        self.btn_jump_top.setEnabled(not self._nav_busy)
        self.btn_jump_top.setToolTip(
            tip_busy if self._nav_busy else "Jump to shaft start (EN2 0)"
        )

    def _reset_tiles_for_new_work(self) -> None:
        """New pool job/block: wipe map paint; keep camera where the digger is."""
        self.canvas.reset_board(reset_pan=False)
        self._session_best = None
        self._sync_depth_nav(busy=False)

    def _merge_board_tiles(self) -> None:
        """
        Soft-load current EN2 board paint into the mega-map.
        Does NOT clear other EN2 islands or snap the camera (EN2 navigate).
        """
        if self._on_reload_tiles is None:
            return
        try:
            rows = self._on_reload_tiles() or []
        except Exception:
            rows = []
        for upd in rows:
            if not isinstance(upd, dict) or upd.get("tile_id") is None:
                continue
            en2 = None
            raw = upd.get("extranonce2")
            if raw is not None:
                try:
                    en2 = int(str(raw), 16)
                except ValueError:
                    en2 = None
            self.canvas.set_tile(
                int(upd["tile_id"]),
                state=str(upd.get("state") or "UNOPENED"),
                best_difficulty=upd.get("best_difficulty"),
                detail=upd,
                extranonce2=en2,
            )

    def _clicked(self, en2: int, tile_id: int) -> None:
        """Enqueue first; only paint QUEUED when the controller accepted it."""
        key = state_key(int(en2), int(tile_id))
        st = self.canvas._states.get(key, "UNOPENED")
        if st not in ("UNOPENED", "INTERRUPTED"):
            return
        ok = False
        try:
            ok = bool(self._on_tile(int(en2), int(tile_id)))
        except Exception:
            ok = False
        if ok:
            self.canvas.set_tile(
                int(tile_id), state="QUEUED", extranonce2=int(en2)
            )
            self._sync_depth_nav(busy=True)
        else:
            # Allow the sweep to retry this cell (do not stick as false QUEUED).
            self.canvas._last_scratch_key = -1

    def apply_stats(self, stats) -> None:
        m = getattr(stats, "game_metrics", None) or {}
        band = self.stats_band
        en2_size = int(m.get("extranonce2_size") or 4)
        live_en2 = int(m.get("live_en2_int") or 0)
        self.canvas.set_map_params(
            extranonce2_size=en2_size, live_en2=live_en2
        )
        queue_len = int(m.get("queue_len") or 0)
        active_tile = m.get("active_tile")
        # Controller is source of truth — paint can lag and must not keep nav locked.
        busy = queue_len > 0 or active_tile is not None
        if not busy:
            self.canvas.clear_stale_inflight_paint()
        self._sync_depth_nav(busy=busy)
        band.card_network.set_value(
            str(getattr(stats, "network_id", None) or "btc").upper()
        )
        job_id = getattr(stats, "current_job_id", None) or m.get("job_id") or "—"
        en2 = m.get("extranonce2") or "—"
        band.card_job.set_value(f"{job_id}\nEN2 {en2}")
        side = board_grid_side(en2_size)
        if side >= 1 << 30:
            depth_label = f"2^{side.bit_length() - 1}"
        elif side >= 10_000:
            depth_label = f"{side:,}"
        else:
            depth_label = str(side)
        board_txt = f"Vertical shaft · {depth_label} deep\nLive EN2 {en2}"
        if m.get("dual_mode"):
            board_txt += (
                f"\nGPU A/G "
                f"{float(m.get('auto_gpu_share_pct') or 0):.0f}/"
                f"{float(m.get('game_gpu_share_pct') or 0):.0f}%"
            )
        band.card_board.set_value(board_txt)
        temp = getattr(stats, "gpu_temp", None)
        paused_th = bool(getattr(stats, "paused_thermal", False))
        if getattr(stats, "temp_readable", False) and temp is not None:
            extra = " · paused" if paused_th else ""
            band.card_temp.set_value(f"{int(temp)}°C{extra}")
        else:
            band.card_temp.set_value(
                "unreadable · mining paused" if paused_th else "unreadable"
            )
        board_rev = int(m.get("tiles_revealed_board") or m.get("tiles_revealed") or 0)
        session_rev = int(
            m.get("tiles_revealed_session")
            or getattr(stats, "game_tiles_revealed", 0)
            or board_rev
        )
        # Mega-map: session total + this EN2 island progress.
        band.card_tiles.set_value(
            f"{session_rev} session\n{board_rev} / {TILE_COUNT} EN2"
        )
        band.card_hashes.set_value(
            f"{int(getattr(stats, 'total_hashes', 0) or 0):,}"
        )
        gpu = getattr(stats, "best_difficulty", None)
        if gpu is not None:
            if self._session_best is None or float(gpu) > float(self._session_best):
                self._session_best = float(gpu)
        band.card_gpu.set_value(format_diff_short(gpu))
        band.card_acc.set_value(
            format_diff_short(getattr(stats, "accepted_best_difficulty", None))
        )
        band.card_session.set_value(format_diff_short(self._session_best))
        acc = int(getattr(stats, "accepted", 0) or 0)
        rej = int(getattr(stats, "rejected", 0) or 0)
        band.card_shares.set_value(f"ACC {acc} · REJ {rej}")
        rate = float(getattr(stats, "hashrate", 0.0) or 0.0)
        if rate >= 1e6:
            band.card_rate.set_value(f"{rate/1e6:.2f} MH/s")
        elif rate >= 1e3:
            band.card_rate.set_value(f"{rate/1e3:.1f} kH/s")
        else:
            band.card_rate.set_value(f"{rate:.0f} H/s")
        hash_s = float(m.get("hashing_time_s") or 0.0)
        band.card_hash_time.set_value(f"{hash_s:.1f} s")

        board_id = str(
            getattr(stats, "game_board_id", None) or m.get("board_id") or ""
        )
        reload_board = bool(getattr(stats, "game_board_reload", False))
        # EN2 / board switch: merge paint only — never snap camera back to live EN2.
        if board_id and board_id != self._active_board_id:
            self._active_board_id = board_id
            self._merge_board_tiles()
        elif reload_board:
            self._active_board_id = board_id
            self._merge_board_tiles()

        ev = str(getattr(stats, "game_event", "") or "")
        detail = str(getattr(stats, "game_event_detail", "") or "")
        event_token = f"{ev}|{detail}|{board_id}"
        if ev and event_token != self._last_game_event:
            self._last_game_event = event_token
            if ev in (
                "new_job",
                "new_block",
                "board_ready",
                "nonce_space_done",
            ):
                if ev in ("new_job", "new_block"):
                    # Pool job change: wipe mega-map + re-center.
                    self._reset_tiles_for_new_work()
                elif ev == "nonce_space_done":
                    # Auto EN2 bump after island complete — keep camera.
                    self._merge_board_tiles()
                elif ev == "board_ready":
                    self._merge_board_tiles()
                if ev == "new_block":
                    band.play_new_work_animation(
                        kind="new_block",
                        title="New Bitcoin Block Detected",
                        message=detail
                        or (
                            "Another block has been detected on the network. "
                            "Tiles reset — preparing the next mining round."
                        ),
                    )
                elif ev == "new_job":
                    band.play_new_work_animation(
                        kind="new_job",
                        title="New Mining Job Received",
                        message=detail
                        or (
                            "The pool has updated your mining work. "
                            "Tiles reset for the new job."
                        ),
                    )
                elif ev == "nonce_space_done":
                    band.play_new_work_animation(
                        kind="board",
                        title="Region Completed",
                        message=detail
                        or "Advancing on the continuous map…",
                    )
                else:
                    band.play_new_work_animation(
                        kind="board",
                        title="Map Ready",
                        message=detail or "Scratch map is ready.",
                    )
            elif detail:
                band.set_event("", detail)

        upd = getattr(stats, "game_tile_update", None)
        if isinstance(upd, dict) and upd.get("tile_id") is not None:
            # Ignore stale updates from a previous board.
            upd_board = str(upd.get("board_id") or "")
            if upd_board and self._active_board_id and upd_board != self._active_board_id:
                return
            tid = int(upd["tile_id"])
            state = str(upd.get("state") or "UNOPENED")
            en2 = None
            raw = upd.get("extranonce2")
            if raw is not None:
                try:
                    en2 = int(str(raw), 16)
                except ValueError:
                    en2 = None
            if en2 is None:
                en2 = int(m.get("live_en2_int") or 0)
            # Reveal only when GPU finished (COMPLETED) or show mid-progress mining.
            if state == "COMPLETED":
                self.canvas.set_tile(
                    tid,
                    state="COMPLETED",
                    best_difficulty=upd.get("best_difficulty"),
                    detail=upd,
                    extranonce2=en2,
                )
            elif state in ("MINING", "QUEUED", "INTERRUPTED", "INVALIDATED"):
                self.canvas.set_tile(
                    tid,
                    state=state,
                    best_difficulty=upd.get("best_difficulty"),
                    detail=upd,
                    extranonce2=en2,
                )
            # Keep nav lock in sync with this tile update + last metrics busy flag.
            if state in ("QUEUED", "MINING"):
                self._sync_depth_nav(busy=True)
            elif not self._nav_busy:
                self._sync_depth_nav(busy=False)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)
