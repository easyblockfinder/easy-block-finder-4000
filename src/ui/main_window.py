"""Single-window Easy Block Finder 4000 UI + system tray."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from app_meta import (
    APP_NAME,
    APP_SHORT,
    APP_TITLE,
    APP_VERSION_LABEL,
    load_app_icon,
    load_app_logo_pixmap,
)
from PyQt6.QtCore import QEvent, QObject, QSize, QThread, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QKeySequence,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from monitor.hardware_gate import network_block_reason
from networks.profiles import get_profile, list_profiles, normalize_network_id
from ui.busy_indicator import BusyIndicator
from ui.donate_dialog import DonateDialog
from ui.hardware_detect_page import HardwareDetectPage
from ui.network_select import NetworkSelectPage
from mining.best_hash import (
    SUPPORTED_BEST_HASH_NETWORKS,
    format_diff_short,
    idle_difficulty_row,
)
from mining.best_hash_store import load_best_hash_state
from ui.scoreboard import ScoreboardOverlayWindow, ScoreboardWidget
from ui.settings_dialog import SettingsDialog
from ui.settings_store import load_settings, save_settings, settings_file
from ui.setup_wizard import SetupWizardPage
from worker.controller import MiningController, MiningStats


class _StopWorker(QThread):
    """Run controller.stop() off the UI thread; result returned via signal."""

    finished_ok = pyqtSignal(bool)

    def __init__(self, controller: MiningController) -> None:
        super().__init__()
        self._controller = controller

    def run(self) -> None:  # noqa: N802
        ok = self._controller.stop()
        self.finished_ok.emit(bool(ok))


class _IdlePrepWorker(QThread):
    """Kill leftover miners off the UI thread (PowerShell must not freeze Continue)."""

    finished_ok = pyqtSignal()

    def run(self) -> None:  # noqa: N802
        try:
            from engines.orphan_miners import kill_app_miners

            kill_app_miners()
        except Exception:
            pass
        self.finished_ok.emit()

APP_QSS = """
QWidget {
    color: #15202b;
}
QMainWindow, QScrollArea, QWidget#root {
    background: #eef1f4;
    color: #15202b;
}
QLabel {
    color: #15202b;
}
QLabel#brand {
    color: #0b3d2e;
    font-size: 28px;
    font-weight: 700;
    letter-spacing: 0.5px;
}
QLabel#tagline {
    color: #4a5a68;
    font-size: 12px;
}
QLabel#sectionTitle {
    color: #0b3d2e;
    font-size: 13px;
    font-weight: 700;
}
QFrame#panel {
    background: #f7f9fb;
    border: 1px solid #d5dde5;
    border-radius: 10px;
}
QFrame#tabSection {
    background: #ffffff;
    border: 1px solid #d5dde5;
    border-radius: 12px;
}
QLabel#tabSectionTitle {
    color: #0b3d2e;
    font-family: "Bahnschrift", "Segoe UI", sans-serif;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.3px;
}
QLabel#tabSectionHint {
    color: #5b6b78;
    font-size: 11px;
}
QFrame#statCell {
    background: #f4f7f9;
    border: 1px solid #e2e8ee;
    border-radius: 10px;
}
QFrame#logPane {
    background: #fbfcfd;
    border: 1px solid #d5dde5;
    border-radius: 12px;
}
QTabWidget#mineTabs::pane {
    background: #eef1f4;
    border: 1px solid #d5dde5;
    border-radius: 12px;
    top: -1px;
    padding: 2px;
}
QTabWidget#mineTabs QTabBar::tab {
    background: #e2e8ee;
    color: #4a5a68;
    border: 1px solid #d5dde5;
    border-bottom: none;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    padding: 9px 16px;
    margin-right: 4px;
    font-family: "Bahnschrift", "Segoe UI", sans-serif;
    font-weight: 600;
    font-size: 12px;
}
QTabWidget#mineTabs QTabBar::tab:selected {
    background: #eef1f4;
    color: #0b3d2e;
    border-top: 2px solid #0d9488;
}
QTabWidget#mineTabs QTabBar::tab:hover:!selected {
    background: #f0f3f6;
    color: #15202b;
}
QComboBox {
    background: #ffffff;
    color: #15202b;
    border: 1px solid #c8d2dc;
    border-radius: 8px;
    padding: 7px 10px;
    min-height: 22px;
    font-size: 13px;
}
QComboBox:focus {
    border: 1px solid #0d9488;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QGroupBox#poolGroup {
    background: #ffffff;
    border: 1px solid #d5dde5;
    border-radius: 12px;
    margin-top: 12px;
    padding: 14px 12px 12px 12px;
    font-family: "Bahnschrift", "Segoe UI", sans-serif;
    font-weight: 700;
    color: #0b3d2e;
}
QGroupBox#poolGroup::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
}
QLineEdit, QSpinBox, QTextEdit, QPlainTextEdit {
    background: #ffffff;
    color: #15202b;
    border: 1px solid #c8d2dc;
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: #0d9488;
    selection-color: #ffffff;
    font-size: 13px;
}
QLineEdit::placeholder, QTextEdit::placeholder, QPlainTextEdit::placeholder {
    color: #94a3b8;
}
QLineEdit:focus, QSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #0d9488;
}
QLineEdit:disabled, QSpinBox:disabled {
    background: #e8edf2;
    color: #6b7c8a;
}
QPushButton#startBtn {
    background: #0d9488;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 700;
    font-size: 12px;
    min-width: 90px;
}
QPushButton#startBtn:hover { background: #0f766e; }
QPushButton#startBtn:disabled { background: #9bb0b8; }
QPushButton#idleStartBtn {
    background: #ffffff;
    color: #0f766e;
    border: 2px solid #0d9488;
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 700;
    font-size: 12px;
    min-width: 110px;
}
QPushButton#idleStartBtn:hover { background: #ecfdf5; }
QPushButton#idleStartBtn:disabled {
    color: #9bb0b8;
    border-color: #c8d2dc;
    background: #f0f3f6;
}
QPushButton#gameModeBtn {
    background: #ffffff;
    color: #0369a1;
    border: 1px solid #0284c7;
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 700;
    font-size: 12px;
    min-width: 110px;
    min-height: 34px;
}
QPushButton#gameModeBtn:hover { background: #f0f9ff; }
QPushButton#gameModeBtn:disabled {
    color: #9bb0b8;
    border-color: #c8d2dc;
    background: #f0f3f6;
}
QLabel#gameModeBetaBadge {
    color: #ffffff;
    background: #ea580c;
    border-radius: 3px;
    padding: 0px 4px;
    font-weight: 800;
    font-size: 8px;
    letter-spacing: 0.3px;
}
QPushButton#stopBtn {
    background: #ffffff;
    color: #9f1239;
    border: 1px solid #e11d48;
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 700;
    font-size: 12px;
    min-width: 90px;
    min-height: 34px;
}
QPushButton#stopBtn:hover { background: #fff1f2; }
QPushButton#stopBtn:disabled {
    color: #9bb0b8;
    border-color: #c8d2dc;
    background: #f0f3f6;
}
QPushButton#changeNetworkBtn {
    background: #ffffff;
    color: #0f766e;
    border: 1px solid #0d9488;
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 700;
    font-size: 12px;
    min-width: 120px;
    min-height: 34px;
}
QPushButton#changeNetworkBtn:hover { background: #ecfdf5; }
QPushButton#changeNetworkBtn:disabled {
    color: #9bb0b8;
    border-color: #c8d2dc;
    background: #f0f3f6;
}
QPushButton#startBtn, QPushButton#idleStartBtn {
    min-height: 34px;
}
QPushButton#supportDevBtn {
    background: #ffffff;
    color: #15202b;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    padding: 3px 9px;
    font-weight: 600;
    font-size: 11px;
    min-height: 22px;
    max-height: 26px;
}
QPushButton#supportDevBtn:hover {
    background: #f8fafc;
    border-color: #9bb0b8;
}
QLabel#unitFixed {
    color: #334155;
    font-size: 13px;
    font-weight: 700;
    padding-left: 2px;
    min-width: 28px;
}
QLabel#statKey {
    color: #5b6b78;
    font-size: 11px;
}
QLabel#statVal {
    color: #15202b;
    font-size: 13px;
    font-weight: 600;
}
QLabel#statValMono {
    color: #15202b;
    font-size: 12px;
    font-family: "Cascadia Mono", "Consolas", monospace;
}
QLabel#statusLine {
    color: #334155;
    font-size: 12px;
    background: #e8f5f2;
    border: 1px solid #b7e0d6;
    border-radius: 8px;
    padding: 8px 10px;
}
QFrame#blockAlert {
    background: #fff7ed;
    border: 2px solid #ea580c;
    border-radius: 10px;
}
QLabel#blockAlertTitle {
    color: #9a3412;
    font-size: 14px;
    font-weight: 700;
}
QLabel#blockAlertBody {
    color: #7c2d12;
    font-size: 12px;
}
QFrame#blockDetail, QFrame#shareDetail {
    background: #ffffff;
    border: 1px solid #d5dde5;
    border-radius: 12px;
}
QPushButton#tabActionBtn {
    background: #ffffff;
    color: #0f766e;
    border: 1px solid #0d9488;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 700;
    font-size: 12px;
}
QPushButton#tabActionBtn:hover { background: #ecfdf5; }
QPushButton#tabActionBtn:disabled {
    color: #9bb0b8;
    border-color: #c8d2dc;
    background: #f0f3f6;
}
QFrame#summaryCard {
    background: #ffffff;
    border: 1px solid #d5dde5;
    border-radius: 8px;
}
QLabel#summaryCardTitle {
    color: #0b3d2e;
    font-family: "Bahnschrift", "Segoe UI", sans-serif;
    font-size: 11px;
    font-weight: 700;
}
QLabel#summaryCap {
    color: #6b7c8a;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.3px;
}
QLabel#summaryVal {
    color: #15202b;
    font-size: 11px;
    font-weight: 700;
}
QLabel#summaryEngine {
    color: #334155;
    font-size: 10px;
    font-weight: 600;
}
QFrame#notesCard {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
}
QLabel#notesTitle {
    color: #1e3a8a;
    font-family: "Bahnschrift", "Segoe UI", sans-serif;
    font-size: 11px;
    font-weight: 700;
}
QLabel#notesBody {
    color: #1e40af;
    font-size: 10px;
}
QLabel#statusChip {
    background: #eef2f6;
    color: #334155;
    border: 1px solid #d5dde5;
    border-radius: 999px;
    padding: 3px 9px;
    font-size: 10px;
    font-weight: 700;
}
QLabel#statusChipOn {
    background: #ecfdf5;
    color: #047857;
    border: 1px solid #a7f3d0;
    border-radius: 999px;
    padding: 3px 9px;
    font-size: 10px;
    font-weight: 700;
}
QLabel#chromeVersion {
    color: #6b7c8a;
    font-size: 10px;
    font-weight: 600;
}
QCheckBox, QRadioButton {
    color: #15202b;
    spacing: 8px;
    font-size: 12px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #c8d2dc;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #0d9488;
    border-color: #0d9488;
}
QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border-radius: 7px;
    border: 1px solid #c8d2dc;
    background: #ffffff;
}
QRadioButton::indicator:checked {
    background: #0d9488;
    border-color: #0d9488;
}
"""


class _StatsBridge(QObject):
    updated = pyqtSignal(object)


def _stat_pair(key: str, mono: bool = False) -> tuple[QLabel, QLabel]:
    k = QLabel(key)
    k.setObjectName("statKey")
    v = QLabel("—")
    v.setObjectName("statValMono" if mono else "statVal")
    v.setWordWrap(True)
    v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    v.setMinimumHeight(22)
    v.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
    return k, v


def _stat_cell(key_lbl: QLabel, val_lbl: QLabel) -> QFrame:
    cell = QFrame()
    cell.setObjectName("statCell")
    lay = QVBoxLayout(cell)
    lay.setContentsMargins(12, 10, 12, 10)
    lay.setSpacing(4)
    lay.addWidget(key_lbl)
    lay.addWidget(val_lbl)
    return cell


def _tab_section(
    title: str, *, hint: str = ""
) -> tuple[QFrame, QVBoxLayout]:
    """Titled content card used inside mining tabs."""
    frame = QFrame()
    frame.setObjectName("tabSection")
    outer = QVBoxLayout(frame)
    outer.setContentsMargins(16, 14, 16, 14)
    outer.setSpacing(10)
    head = QVBoxLayout()
    head.setSpacing(3)
    t = QLabel(title)
    t.setObjectName("tabSectionTitle")
    head.addWidget(t)
    if hint:
        h = QLabel(hint)
        h.setObjectName("tabSectionHint")
        h.setWordWrap(True)
        head.addWidget(h)
    outer.addLayout(head)
    body = QVBoxLayout()
    body.setSpacing(10)
    outer.addLayout(body)
    return frame, body


def _stats_grid(pairs: list[tuple[QLabel, QLabel]], *, cols: int = 2) -> QGridLayout:
    grid = QGridLayout()
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(10)
    for i in range(cols):
        grid.setColumnStretch(i, 1)
    for i, (k, v) in enumerate(pairs):
        r, c = divmod(i, cols)
        grid.addWidget(_stat_cell(k, v), r, c)
    return grid


def _summary_field(caption: str) -> tuple[QWidget, QLabel]:
    wrap = QWidget()
    lay = QVBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    cap = QLabel(caption.upper())
    cap.setObjectName("summaryCap")
    val = QLabel("—")
    val.setObjectName("summaryVal")
    val.setWordWrap(True)
    lay.addWidget(cap)
    lay.addWidget(val)
    return wrap, val


def _status_chip(text: str, *, on: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("statusChipOn" if on else "statusChip")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl


def _support_heart_icon() -> QIcon:
    """Outlined red heart for Support Development (no emoji glyph)."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen

    size = 28
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.moveTo(14, 24)
    path.cubicTo(QPointF(4, 17), QPointF(3, 9), QPointF(8.5, 6.5))
    path.cubicTo(QPointF(11.5, 5), QPointF(14, 7), QPointF(14, 9.5))
    path.cubicTo(QPointF(14, 7), QPointF(16.5, 5), QPointF(19.5, 6.5))
    path.cubicTo(QPointF(25, 9), QPointF(24, 17), QPointF(14, 24))
    pen = QPen(QColor("#e11d48"))
    pen.setWidthF(2.2)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.end()
    return QIcon(pix)


def _temp_spin_row(spin: QSpinBox) -> QWidget:
    """Digit SpinBox + fixed °C label (unit cannot be removed)."""
    wrap = QWidget()
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    spin.setMinimumHeight(34)
    spin.setSuffix("")  # unit in separate label
    unit = QLabel("°C")
    unit.setObjectName("unitFixed")
    unit.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    lay.addWidget(spin, 1)
    lay.addWidget(unit, 0)
    return wrap


def _make_tray_icon() -> QIcon:
    icon = load_app_icon()
    if not icon.isNull():
        return icon
    # Fallback if asset missing
    pix = QPixmap(64, 64)
    pix.fill(QColor("#0a1628"))
    return QIcon(pix)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setStyleSheet(APP_QSS)

        self._cfg = load_settings()
        self._network_id = normalize_network_id(str(self._cfg.get("selected_network") or "btc"))
        self._profile = get_profile(self._network_id)
        w = int(self._cfg.get("window_width") or 760)
        h = int(self._cfg.get("window_height") or 720)
        self.setMinimumSize(820, 620)
        self._clamp_window_to_screen(preferred_w=max(820, w), preferred_h=max(640, h))

        self._bridge = _StatsBridge()
        self._bridge.updated.connect(self._apply_stats)
        self.controller = MiningController(on_stats=self._bridge.updated.emit)
        if bool(self._cfg.get("mining_audit_live_enabled", False)):
            self.controller.set_live_audit(True)
        if bool(self._cfg.get("stratum_work_ledger_enabled", False)):
            self.controller.set_work_ledger(True)
        self._stop_worker: _StopWorker | None = None
        self._stop_busy = False
        self._pending_quit = False
        self._last_thermal_paused: bool | None = None
        self._last_block_notify_key: str | None = None
        self._tray_exit = False
        self._tray_minimize_tip_shown = False
        self._scoreboard_hide_tip_shown = False
        self._stats_url = ""
        self._defender_help_shown = False
        self._update_check_worker = None
        self._update_prepare_worker = None
        self._update_progress_dlg = None
        self._pending_update = None  # PreparedUpdate while stopping for apply
        self._miner_dl_worker = None
        self._miner_dl_dialog = None
        self._after_miner_download = None  # optional Callable[[], None]
        self._capacity_worker = None
        self._idle_prep_worker: _IdlePrepWorker | None = None
        self._capacity_blocks = self._load_capacity_blocks()
        self._last_scoreboard = (0, 0, 0, 0)  # blocks, accepted, rejected, attempts
        self._last_scoreboard_temp: int | None = None
        self._last_net_diff: float | None = None
        self._last_best_diff: float | None = None
        self._last_accepted_best_diff: float | None = None
        self._last_accepted_diff: float | None = None  # session LAST ACC
        self._scoreboard_overlay: ScoreboardOverlayWindow | None = None
        self._quit_busy_host: QWidget | None = None
        self._quit_busy: BusyIndicator | None = None
        self._game_busy_host: QWidget | None = None
        self._game_busy: BusyIndicator | None = None

        self._build_menu()

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # 0: setup wizard → 1: network select → 2: optional hardware → 3: mining
        self._setup_wizard = SetupWizardPage(self._cfg)
        self._setup_wizard.finished.connect(self._on_setup_wizard_finished)
        self._stack.addWidget(self._setup_wizard)

        self._select_page = NetworkSelectPage(
            self._network_id,
            blocked=self._network_blocked_map(),
            show_hardware_button=True,
        )
        self._select_page.network_chosen.connect(self._on_network_chosen)
        self._select_page.hardware_check_clicked.connect(self._on_open_hardware_check)
        self._stack.addWidget(self._select_page)

        self._hw_page = HardwareDetectPage()
        self._hw_page.continue_clicked.connect(self._on_hardware_continue)
        self._hw_page.back_clicked.connect(self._on_hardware_back_to_network)
        self._stack.addWidget(self._hw_page)

        # Mining page: fixed header + tabs (scroll only inside tabs)
        mine_page = QWidget()
        mine_page.setObjectName("root")
        self._mine_scroll = mine_page  # page widget (name kept for call sites)
        self._stack.addWidget(mine_page)

        layout = QVBoxLayout(mine_page)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        def _tab_scroll(inner: QWidget) -> QScrollArea:
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.Shape.NoFrame)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            sa.setWidget(inner)
            return sa

        # Fixed chrome matching dashboard mock (scoreboard + summary + controls)
        header = QWidget()
        header.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        logo_pix = load_app_logo_pixmap(360, 72)
        brand = QLabel()
        brand.setObjectName("brand")
        if not logo_pix.isNull():
            brand.setPixmap(logo_pix)
            brand.setMinimumHeight(56)
        else:
            brand.setText(APP_NAME)
            brand.setFont(QFont("Bahnschrift", 22, QFont.Weight.Bold))
        brand_col = QVBoxLayout()
        brand_col.setSpacing(2)
        brand_col.addWidget(brand)
        ver = QLabel(APP_VERSION_LABEL)
        ver.setObjectName("chromeVersion")
        brand_col.addWidget(ver)
        brand_row.addLayout(brand_col, 0)
        brand_row.addStretch(1)
        h_layout.addLayout(brand_row)

        # Scoreboard + cards + controls share one left-aligned band (no right overflow).
        self._chrome_band = QWidget()
        self._chrome_band.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        band = QVBoxLayout(self._chrome_band)
        band.setContentsMargins(0, 0, 0, 0)
        band.setSpacing(8)

        self.scoreboard = ScoreboardWidget(compact=False)
        band.addWidget(self.scoreboard, 0, Qt.AlignmentFlag.AlignLeft)

        self._scoreboard_overlay = ScoreboardOverlayWindow(
            on_user_close=self._on_scoreboard_overlay_closed,
            parent=None,
        )
        self._scoreboard_overlay.activated.connect(self._show_from_tray)

        cards_w = QWidget()
        cards_w.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        cards = QHBoxLayout(cards_w)
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(8)

        net_card = QFrame()
        net_card.setObjectName("summaryCard")
        net_lay = QVBoxLayout(net_card)
        net_lay.setContentsMargins(8, 6, 8, 6)
        net_lay.setSpacing(4)
        net_title = QLabel("Network summary")
        net_title.setObjectName("summaryCardTitle")
        net_lay.addWidget(net_title)
        fields = QHBoxLayout()
        fields.setSpacing(8)
        w_net, self.lbl_sum_network = _summary_field("Network")
        w_algo, self.lbl_sum_algo = _summary_field("Algorithm")
        w_pool, self.lbl_sum_pool = _summary_field("Pool")
        w_mode, self.lbl_sum_mode = _summary_field("Mode")
        for w in (w_net, w_algo, w_pool, w_mode):
            fields.addWidget(w, 1)
        net_lay.addLayout(fields)
        self.lbl_sum_engine = QLabel("Engine: —")
        self.lbl_sum_engine.setObjectName("summaryEngine")
        self.lbl_sum_engine.setWordWrap(True)
        net_lay.addWidget(self.lbl_sum_engine)
        # Keep legacy labels for call sites (hidden)
        self.lbl_network_badge = QLabel("")
        self.lbl_network_badge.hide()
        self.lbl_tagline = QLabel("")
        self.lbl_tagline.hide()
        cards.addWidget(net_card, 3)

        notes_card = QFrame()
        notes_card.setObjectName("notesCard")
        notes_lay = QVBoxLayout(notes_card)
        notes_lay.setContentsMargins(8, 6, 8, 6)
        notes_lay.setSpacing(3)
        notes_title = QLabel("Mining notes")
        notes_title.setObjectName("notesTitle")
        notes_lay.addWidget(notes_title)
        notes_body = QLabel(
            "Share difficulty is pool feedback only — it does not change block odds. "
            "Accepted rises only when mining.submit returns result=true."
        )
        notes_body.setObjectName("notesBody")
        notes_body.setWordWrap(True)
        notes_lay.addWidget(notes_body)
        cards.addWidget(notes_card, 2)
        band.addWidget(cards_w)

        ctrl_w = QWidget()
        ctrl_w.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        ctrl = QHBoxLayout(ctrl_w)
        ctrl.setContentsMargins(0, 0, 0, 0)
        ctrl.setSpacing(10)
        self.start_btn = QPushButton("▶  Start")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.idle_start_btn = QPushButton("Start Idle Mode")
        self.idle_start_btn.setObjectName("idleStartBtn")
        self.idle_start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.idle_start_btn.setToolTip(
            "Start Idle Mode: mining begins now at “While using PC” intensity; "
            "after the AFK timeout it switches to “While AFK” intensity. "
            "Configure under Settings → Idle Mode."
        )
        self.game_btn = QPushButton("Game Mode")
        self.game_btn.setObjectName("gameModeBtn")
        self.game_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.game_btn.setToolTip(
            "Scratch Mining: real SHA256d when you click a tile (BTC native). "
            "Can run together with Start — GPU splits ~50/50."
        )
        self._game_beta_badge = QLabel("BETA", self.game_btn)
        self._game_beta_badge.setObjectName("gameModeBetaBadge")
        self._game_beta_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._game_beta_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._game_beta_badge.adjustSize()
        self.game_btn.installEventFilter(self)
        QTimer.singleShot(0, self._position_game_beta_badge)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setEnabled(False)
        self.btn_change_network = QPushButton("Change network")
        self.btn_change_network.setObjectName("changeNetworkBtn")
        self.btn_change_network.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_change_network.clicked.connect(self._on_change_network)
        self.start_btn.clicked.connect(self._on_start)
        self.idle_start_btn.clicked.connect(self._on_start_idle)
        self.game_btn.clicked.connect(self._on_start_game)
        self.stop_btn.clicked.connect(self._on_stop)
        for b in (
            self.start_btn,
            self.idle_start_btn,
            self.game_btn,
            self.stop_btn,
            self.btn_change_network,
        ):
            b.setMinimumHeight(34)
            b.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
            )
            ctrl.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        ctrl.addSpacing(12)
        self.chip_conn = _status_chip("Not connected", on=False)
        self.chip_mode = _status_chip("Solo mining", on=False)
        self.chip_idle = _status_chip("Idle Mode off", on=False)
        for chip in (self.chip_conn, self.chip_mode, self.chip_idle):
            ctrl.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        ctrl.addStretch(1)
        self._ctrl_row = ctrl_w
        band.addWidget(ctrl_w)

        h_layout.addWidget(self._chrome_band, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(header, 0)
        QTimer.singleShot(0, self._fit_chrome_to_scoreboard)

        from worker.idle_session import IdleSessionState

        self._idle_state = IdleSessionState.STOPPED
        self._idle_launching = False
        self._pending_session_kind = "auto"
        self._scratch_window = None

        tabs = QTabWidget()
        tabs.setObjectName("mineTabs")
        tabs.setDocumentMode(True)
        tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._mine_tabs = tabs

        self.btn_donate = QPushButton(" Support Development")
        self.btn_donate.setObjectName("supportDevBtn")
        self.btn_donate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_donate.setIcon(_support_heart_icon())
        self.btn_donate.setIconSize(QSize(11, 11))
        self.btn_donate.clicked.connect(self._on_donate)
        corner = QWidget()
        corner_lay = QHBoxLayout(corner)
        corner_lay.setContentsMargins(0, 0, 2, 2)
        corner_lay.setSpacing(0)
        corner_lay.addWidget(self.btn_donate)
        tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        # --- Settings (default) ---
        settings = QWidget()
        s_layout = QVBoxLayout(settings)
        s_layout.setContentsMargins(16, 14, 16, 14)
        s_layout.setSpacing(12)

        pay_card, pay_body = _tab_section(
            "Payout address",
            hint="Saved per network. Pool host and TLS live on the Mining pool tab.",
        )
        self.addr_lbl = QLabel("Wallet / payout address")
        self.addr_lbl.setObjectName("statKey")
        pay_body.addWidget(self.addr_lbl)
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText(
            "network wallet address — saved automatically"
        )
        self.address_edit.setMinimumHeight(40)
        self.address_edit.setFont(QFont("Cascadia Mono", 11))
        self.address_edit.editingFinished.connect(self._persist_form)
        self.address_edit.textChanged.connect(self._on_address_changed)
        pay_body.addWidget(self.address_edit)
        self._addr_hint = QLabel("")
        self._addr_hint.setObjectName("tabSectionHint")
        self._addr_hint.setWordWrap(True)
        pay_body.addWidget(self._addr_hint)
        self._refresh_addr_hint()
        s_layout.addWidget(pay_card)

        sess_card, sess_body = _tab_section(
            "Session",
            hint="Intensity, temps, and Idle Mode: Settings menu → Mining Settings.",
        )
        self.test_mode = QCheckBox("Test mode (no pool, no real submit)")
        self.test_mode.setChecked(bool(self._cfg.get("test_mode")))
        self.test_mode.toggled.connect(self._persist_form)
        sess_body.addWidget(self.test_mode)

        strat_row = QHBoxLayout()
        strat_row.setSpacing(8)
        self.lbl_search_strategy = QLabel("Search strategy")
        self.lbl_search_strategy.setObjectName("statKey")
        strat_row.addWidget(self.lbl_search_strategy, 0)
        self.search_strategy = QComboBox()
        self.search_strategy.setMinimumHeight(34)
        self.search_strategy.addItem("Sequential (default)", "sequential")
        self.search_strategy.addItem("Reverse", "reverse")
        self.search_strategy.addItem("Randomized", "randomized")
        self.search_strategy.setToolTip(
            "BTC/BCH nonce search order only — does not increase block odds."
        )
        raw_strat = str(self._cfg.get("mining_search_strategy") or "sequential").lower()
        idx = max(0, self.search_strategy.findData(raw_strat))
        self.search_strategy.setCurrentIndex(idx if idx >= 0 else 0)
        self.search_strategy.currentIndexChanged.connect(self._on_search_strategy_changed)
        strat_row.addWidget(self.search_strategy, 1)
        sess_body.addLayout(strat_row)
        self.lbl_search_strategy_hint = QLabel("")
        self.lbl_search_strategy_hint.setVisible(False)
        s_layout.addWidget(sess_card)

        health_card, health_body = _tab_section(
            "Status",
            hint="Live thermal source and third-party engine fee shares.",
        )
        self.lbl_thermal_src = QLabel("Temperature source: —")
        self.lbl_thermal_src.setObjectName("statKey")
        self.lbl_thermal_src.setWordWrap(True)
        health_body.addWidget(self.lbl_thermal_src)
        self.lbl_thermal_unsafe = QLabel("")
        self.lbl_thermal_unsafe.setWordWrap(True)
        self.lbl_thermal_unsafe.setStyleSheet(
            "color: #b91c1c; font-weight: 700; padding: 6px 8px; "
            "background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px;"
        )
        self.lbl_thermal_unsafe.setVisible(False)
        health_body.addWidget(self.lbl_thermal_unsafe)
        self._refresh_thermal_unsafe_banner()
        fee_row = QHBoxLayout()
        fee_row.setSpacing(10)
        self.lbl_engine_fee = QLabel("Engine fee share: 0")
        self.lbl_engine_fee.setObjectName("statKey")
        self.lbl_unattributed = QLabel("Unattributed shares: 0")
        self.lbl_unattributed.setObjectName("statKey")
        fee_row.addWidget(self.lbl_engine_fee, 1)
        fee_row.addWidget(self.lbl_unattributed, 1)
        health_body.addLayout(fee_row)
        s_layout.addWidget(health_card)
        s_layout.addStretch(1)
        tabs.addTab(_tab_scroll(settings), "Settings")

        # --- Mining pool ---
        from ui.pool_settings_panel import PoolSettingsPanel

        pool_tab = QWidget()
        p_layout = QVBoxLayout(pool_tab)
        p_layout.setContentsMargins(16, 14, 16, 14)
        p_layout.setSpacing(12)
        self.pool_panel = PoolSettingsPanel(
            is_running=lambda: self.controller.is_running()
            or self._idle_session_active(),
            request_stop=self._on_stop,
            get_wallet=lambda: self.address_edit.text(),
        )
        self.pool_panel.on_applied = self._on_pool_applied
        self.pool_panel.load_network(
            self._network_id, self._cfg.get("pool_by_network") or {}
        )
        p_layout.addWidget(self.pool_panel)
        self.lbl_pool_banner = QLabel("")
        self.lbl_pool_banner.setWordWrap(True)
        self.lbl_pool_banner.setStyleSheet(
            "color: #b91c1c; font-weight: 600; padding: 8px 10px; "
            "background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px;"
        )
        self.lbl_pool_banner.setVisible(False)
        p_layout.addWidget(self.lbl_pool_banner)
        p_layout.addStretch(1)
        tabs.addTab(_tab_scroll(pool_tab), "Mining pool")

        # --- Status ---
        status = QWidget()
        st_outer = QVBoxLayout(status)
        st_outer.setContentsMargins(16, 14, 16, 14)
        st_outer.setSpacing(12)

        self.lbl_conn_k, self.lbl_conn = _stat_pair("Connection")
        self.lbl_activity_k, self.lbl_activity = _stat_pair("Idle Mode")
        self.lbl_device_k, self.lbl_device = _stat_pair("Device")
        self.lbl_rate_k, self.lbl_rate = _stat_pair("Hash rate")
        self.lbl_temp_k, self.lbl_temp = _stat_pair("Temperature")
        self.lbl_time_k, self.lbl_time = _stat_pair("Elapsed")
        live_card, live_body = _tab_section(
            "Live session",
            hint="Connection, device load, and Idle Mode state.",
        )
        live_body.addLayout(
            _stats_grid(
                [
                    (self.lbl_conn_k, self.lbl_conn),
                    (self.lbl_activity_k, self.lbl_activity),
                    (self.lbl_device_k, self.lbl_device),
                    (self.lbl_rate_k, self.lbl_rate),
                    (self.lbl_temp_k, self.lbl_temp),
                    (self.lbl_time_k, self.lbl_time),
                ]
            )
        )
        st_outer.addWidget(live_card)

        self.lbl_total_k, self.lbl_total = _stat_pair("Session attempts", mono=True)
        self.lbl_lifetime_k, self.lbl_lifetime = _stat_pair("Lifetime attempts", mono=True)
        self.lbl_shares_k, self.lbl_shares = _stat_pair("Share")
        self.lbl_diff_k, self.lbl_diff = _stat_pair("Server set_difficulty")
        self.lbl_gpu_best_k, self.lbl_gpu_best = _stat_pair("GPU best difficulty")
        self.lbl_acc_best_k, self.lbl_acc_best = _stat_pair("Accepted best difficulty")
        work_card, work_body = _tab_section(
            "Work & difficulty",
            hint="Attempts and difficulty telemetry for this session.",
        )
        work_body.addLayout(
            _stats_grid(
                [
                    (self.lbl_total_k, self.lbl_total),
                    (self.lbl_lifetime_k, self.lbl_lifetime),
                    (self.lbl_shares_k, self.lbl_shares),
                    (self.lbl_diff_k, self.lbl_diff),
                    (self.lbl_gpu_best_k, self.lbl_gpu_best),
                    (self.lbl_acc_best_k, self.lbl_acc_best),
                ]
            )
        )
        st_outer.addWidget(work_card)

        self.lbl_job_k, self.lbl_job = _stat_pair("Current job ID", mono=True)
        self.lbl_payout_k, self.lbl_payout = _stat_pair("Payout address", mono=True)
        self.lbl_coinbase_k, self.lbl_coinbase = _stat_pair("Coinbase / note")
        job_card, job_body = _tab_section("Job & payout")
        job_body.addLayout(
            _stats_grid(
                [
                    (self.lbl_job_k, self.lbl_job),
                    (self.lbl_payout_k, self.lbl_payout),
                    (self.lbl_coinbase_k, self.lbl_coinbase),
                ],
                cols=1,
            )
        )
        st_outer.addWidget(job_card)

        self.lbl_accepted_best_banner = QLabel("")
        self.lbl_accepted_best_banner.setObjectName("acceptedBestBanner")
        self.lbl_accepted_best_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_accepted_best_banner.setVisible(False)
        self.lbl_accepted_best_banner.setStyleSheet(
            "color: #14532d; font-weight: 700; padding: 8px; "
            "background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px;"
        )
        st_outer.addWidget(self.lbl_accepted_best_banner)
        self._accepted_best_banner_timer = QTimer(self)
        self._accepted_best_banner_timer.setSingleShot(True)
        self._accepted_best_banner_timer.timeout.connect(self._hide_accepted_best_banner)

        run_card, run_body = _tab_section("Runtime")
        self.lbl_work = QLabel("no kernel yet (connected ≠ hashing)")
        self.lbl_work.setObjectName("statValMono")
        self.lbl_work.setWordWrap(True)
        self.lbl_work.setMinimumHeight(36)
        self.lbl_work.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        run_body.addWidget(self.lbl_work)
        self.lbl_status = QLabel("Ready")
        self.lbl_status.setObjectName("statusLine")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setMinimumHeight(40)
        run_body.addWidget(self.lbl_status)
        st_outer.addWidget(run_card)

        pool_card, pool_body = _tab_section(
            "Pool page",
            hint="Server stats may lag at low hashrate or high mindiff.",
        )
        stats_row = QHBoxLayout()
        self.lbl_stats_url = QLabel("Pool stats: —")
        self.lbl_stats_url.setObjectName("statKey")
        self.lbl_stats_url.setWordWrap(True)
        self.btn_stats = QPushButton("Open pool page")
        self.btn_stats.setObjectName("tabActionBtn")
        self.btn_stats.setEnabled(False)
        self.btn_stats.clicked.connect(self._open_ckpool_stats)
        stats_row.addWidget(self.lbl_stats_url, 1)
        stats_row.addWidget(self.btn_stats, 0)
        pool_body.addLayout(stats_row)
        self.lbl_stats_hint = QLabel("")
        self.lbl_stats_hint.setObjectName("tabSectionHint")
        self.lbl_stats_hint.setWordWrap(True)
        self.lbl_stats_hint.setVisible(False)
        pool_body.addWidget(self.lbl_stats_hint)
        st_outer.addWidget(pool_card)

        sub_card, sub_body = _tab_section(
            "mining.submit log",
            hint="Request/response pairs match by id. Accepted only when result=true.",
        )
        self.submit_log_view = QTextEdit()
        self.submit_log_view.setReadOnly(True)
        self.submit_log_view.setMinimumHeight(110)
        self.submit_log_view.setFont(QFont("Cascadia Mono", 9))
        self.submit_log_view.setPlaceholderText(
            "Submit traffic appears here while mining."
        )
        sub_body.addWidget(self.submit_log_view, 1)
        st_outer.addWidget(sub_card, 1)
        tabs.addTab(_tab_scroll(status), "Status")

        # --- Block ---
        block_tab = QWidget()
        bp = QVBoxLayout(block_tab)
        bp.setContentsMargins(16, 14, 16, 14)
        bp.setSpacing(12)

        self.block_alert = QFrame()
        self.block_alert.setObjectName("blockAlert")
        self.block_alert.setVisible(False)
        ba = QVBoxLayout(self.block_alert)
        ba.setContentsMargins(14, 12, 14, 12)
        ba.setSpacing(6)
        self.lbl_block_alert_title = QLabel("BLOCK CANDIDATE")
        self.lbl_block_alert_title.setObjectName("blockAlertTitle")
        ba.addWidget(self.lbl_block_alert_title)
        self.lbl_block_alert_body = QLabel("")
        self.lbl_block_alert_body.setObjectName("blockAlertBody")
        self.lbl_block_alert_body.setWordWrap(True)
        ba.addWidget(self.lbl_block_alert_body)
        bp.addWidget(self.block_alert)

        blk_card, blk_body = _tab_section(
            "Latest candidate",
            hint="No payout until the network accepts the block — candidates only.",
        )
        self.lbl_blk_count_k, self.lbl_blk_count = _stat_pair("Candidate count")
        self.lbl_blk_time_k, self.lbl_blk_time = _stat_pair("Time")
        self.lbl_blk_nonce_k, self.lbl_blk_nonce = _stat_pair("Nonce", mono=True)
        self.lbl_blk_job_k, self.lbl_blk_job = _stat_pair("Job ID", mono=True)
        self.lbl_blk_status_k, self.lbl_blk_status = _stat_pair("Submit / pool")
        self.lbl_blk_chain_k, self.lbl_blk_chain = _stat_pair("Chain status")
        self.lbl_blk_hash_k, self.lbl_blk_hash = _stat_pair("Hash", mono=True)
        blk_body.addLayout(
            _stats_grid(
                [
                    (self.lbl_blk_count_k, self.lbl_blk_count),
                    (self.lbl_blk_time_k, self.lbl_blk_time),
                    (self.lbl_blk_nonce_k, self.lbl_blk_nonce),
                    (self.lbl_blk_job_k, self.lbl_blk_job),
                    (self.lbl_blk_status_k, self.lbl_blk_status),
                    (self.lbl_blk_chain_k, self.lbl_blk_chain),
                ]
            )
        )
        hash_cell = _stat_cell(self.lbl_blk_hash_k, self.lbl_blk_hash)
        self.lbl_blk_hash.setMinimumHeight(40)
        blk_body.addWidget(hash_cell)
        bp.addWidget(blk_card)

        hist_card, hist_body = _tab_section("Candidate history")
        self.block_list = QTextEdit()
        self.block_list.setObjectName("logPane")
        self.block_list.setReadOnly(True)
        self.block_list.setMinimumHeight(120)
        self.block_list.setPlaceholderText("No block candidates yet (expected).")
        self.block_list.setFont(QFont("Cascadia Mono", 10))
        hist_body.addWidget(self.block_list, 1)
        bp.addWidget(hist_card, 1)
        tabs.addTab(_tab_scroll(block_tab), "Block")

        # --- Shares ---
        share_tab = QWidget()
        sp = QVBoxLayout(share_tab)
        sp.setContentsMargins(16, 14, 16, 14)
        sp.setSpacing(12)
        sh_card, sh_body = _tab_section(
            "Share summary",
            hint="Pool target shares — not a block reward.",
        )
        self.lbl_sh_count_k, self.lbl_sh_count = _stat_pair("Submitted")
        self.lbl_sh_acc_k, self.lbl_sh_acc = _stat_pair("Accepted / rejected")
        self.lbl_sh_nonce_k, self.lbl_sh_nonce = _stat_pair("Last nonce", mono=True)
        self.lbl_sh_status_k, self.lbl_sh_status = _stat_pair("Last status")
        self.lbl_sh_hash_k, self.lbl_sh_hash = _stat_pair("Last hash", mono=True)
        sh_body.addLayout(
            _stats_grid(
                [
                    (self.lbl_sh_count_k, self.lbl_sh_count),
                    (self.lbl_sh_acc_k, self.lbl_sh_acc),
                    (self.lbl_sh_nonce_k, self.lbl_sh_nonce),
                    (self.lbl_sh_status_k, self.lbl_sh_status),
                ]
            )
        )
        sh_body.addWidget(_stat_cell(self.lbl_sh_hash_k, self.lbl_sh_hash))
        self.lbl_sh_hash.setMinimumHeight(36)
        sp.addWidget(sh_card)

        sh_hist, sh_hist_body = _tab_section("Share log")
        self.share_list = QTextEdit()
        self.share_list.setReadOnly(True)
        self.share_list.setMinimumHeight(120)
        self.share_list.setPlaceholderText("No shares yet.")
        self.share_list.setFont(QFont("Cascadia Mono", 10))
        sh_hist_body.addWidget(self.share_list, 1)
        sp.addWidget(sh_hist, 1)
        tabs.addTab(_tab_scroll(share_tab), "Shares")

        # --- Event log ---
        log_tab = QWidget()
        lp = QVBoxLayout(log_tab)
        lp.setContentsMargins(16, 14, 16, 14)
        lp.setSpacing(12)
        log_card, log_body = _tab_section(
            "Event log",
            hint="Jobs, shares, block candidates, and pool replies.",
        )
        self.event_log = QTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setMinimumHeight(220)
        self.event_log.setPlaceholderText(
            "Activity appears here once mining starts."
        )
        self.event_log.setFont(QFont("Cascadia Mono", 10))
        log_body.addWidget(self.event_log, 1)
        lp.addWidget(log_card, 1)
        tabs.addTab(_tab_scroll(log_tab), "Event log")

        tabs.setCurrentIndex(0)  # Settings active by default
        layout.addWidget(tabs, 1)
        from ui.wheel_guard import harden_wheel_widgets

        harden_wheel_widgets(mine_page)

        foot = QLabel(f"Settings file: {settings_file()}")
        foot.setObjectName("statKey")
        foot.setWordWrap(True)
        foot.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(foot, 0)

        self._addr_save_timer = QTimer(self)
        self._addr_save_timer.setSingleShot(True)
        self._addr_save_timer.timeout.connect(self._persist_form)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._push_settings)
        self._timer.start(1000)

        self.lbl_rate.setText("0 H/s")
        self.lbl_total.setText("0")
        try:
            from mining.lifetime_stats import get_lifetime_attempts

            self.lbl_lifetime.setText(f"{get_lifetime_attempts(self._network_id):,}")
        except Exception:
            self.lbl_lifetime.setText("0")
        self.lbl_time.setText("0s")
        self.lbl_shares.setText("accepted 0 / rejected 0")
        self.lbl_conn.setText("Not connected")
        self.lbl_blk_count.setText("0")
        self.lbl_blk_time.setText("—")
        self.lbl_blk_nonce.setText("—")
        self.lbl_blk_job.setText("—")
        self.lbl_blk_status.setText("None yet")
        self.lbl_blk_chain.setText("—")
        self.lbl_blk_hash.setText("—")
        self.lbl_coinbase.setText("—")
        self.lbl_sh_count.setText("0")
        self.lbl_sh_acc.setText("0 / 0")
        self.lbl_sh_nonce.setText("—")
        self.lbl_sh_status.setText("None yet")
        self.lbl_sh_hash.setText("—")

        self._setup_tray()
        self._apply_network_to_ui()
        self._load_stored_best_into_row()
        self._apply_idle_mining_ui()
        if not bool(self._cfg.get("setup_wizard_done")):
            self._stack.setCurrentWidget(self._setup_wizard)
        else:
            self._stack.setCurrentWidget(self._select_page)
        QTimer.singleShot(50, self._startup_clear_orphans)
        QTimer.singleShot(400, self._maybe_offer_missing_miners)
        # Every launch: check GitHub and ask if a newer signed release exists
        QTimer.singleShot(
            2000, lambda: self._check_for_updates(manual=False, every_launch=True)
        )

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        act_wiz = QAction("Run Setup Wizard…", self)
        act_wiz.triggered.connect(self._rerun_setup_wizard)
        file_menu.addAction(act_wiz)
        file_menu.addSeparator()
        act_restart = QAction("Restart Mining Session", self)
        act_restart.triggered.connect(self._restart_mining_session)
        file_menu.addAction(act_restart)
        act_logs = QAction("View Logs…", self)
        act_logs.triggered.connect(self._view_event_logs)
        file_menu.addAction(act_logs)
        file_menu.addSeparator()
        act_exit = QAction("E&xit", self)
        act_exit.triggered.connect(self._quit_from_menu)
        file_menu.addAction(act_exit)

        settings_menu = self.menuBar().addMenu("&Settings")
        act_mining = QAction("Mining Settings…", self)
        act_mining.triggered.connect(lambda: self._open_settings(focus="mining"))
        settings_menu.addAction(act_mining)
        act_idle = QAction("Idle Mode Settings…", self)
        act_idle.triggered.connect(lambda: self._open_settings(focus="idle"))
        settings_menu.addAction(act_idle)
        act_hw = QAction("Hardware & Temperature…", self)
        act_hw.triggered.connect(lambda: self._open_settings(focus="hardware"))
        settings_menu.addAction(act_hw)
        act_conn = QAction("Connection Settings…", self)
        act_conn.triggered.connect(self._open_connection_settings)
        settings_menu.addAction(act_conn)
        settings_menu.addSeparator()
        act_reset = QAction("Reset Settings…", self)
        act_reset.triggered.connect(self._reset_settings)
        settings_menu.addAction(act_reset)

        tools_menu = self.menuBar().addMenu("&Tools")
        act_bench = QAction("Benchmark…", self)
        act_bench.triggered.connect(self._run_benchmark)
        tools_menu.addAction(act_bench)
        act_diag = QAction("Mining Diagnostics…", self)
        act_diag.triggered.connect(self._show_mining_diagnostics)
        tools_menu.addAction(act_diag)
        act_audit = QAction("Mining Statistical Audit…", self)
        act_audit.triggered.connect(self._show_mining_audit)
        tools_menu.addAction(act_audit)

        view_menu = self.menuBar().addMenu("&View")
        act_max = QAction("Maximize", self)
        act_max.setShortcut(QKeySequence(Qt.Key.Key_F11))
        act_max.triggered.connect(self._toggle_maximize)
        view_menu.addAction(act_max)

        help_menu = self.menuBar().addMenu("&Help")
        act_how = QAction("How to Use…", self)
        act_how.triggered.connect(self._show_howto)
        help_menu.addAction(act_how)
        act_upd = QAction("Check for Updates…", self)
        act_upd.triggered.connect(lambda: self._check_for_updates(manual=True))
        help_menu.addAction(act_upd)
        help_menu.addSeparator()
        act_issue = QAction("Report an Issue…", self)
        act_issue.triggered.connect(self._report_issue)
        help_menu.addAction(act_issue)
        act_fb = QAction("Feedback & Suggestions…", self)
        act_fb.triggered.connect(self._show_feedback)
        help_menu.addAction(act_fb)
        act_gh = QAction("GitHub Repository", self)
        act_gh.triggered.connect(self._open_github)
        help_menu.addAction(act_gh)
        help_menu.addSeparator()
        act_about = QAction(f"About {APP_SHORT}…", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _toggle_maximize(self, *_args) -> None:
        """Title-bar maximize (□) equivalent — F11 / View menu."""
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        else:
            self.showMaximized()

    def _show_howto(self) -> None:
        from ui.howto_dialog import HowToUseDialog

        HowToUseDialog(self).exec()

    def _show_feedback(self) -> None:
        from ui.feedback_dialog import FeedbackDialog

        FeedbackDialog(self).exec()

    def _show_about(self) -> None:
        from ui.about_dialog import AboutDialog

        AboutDialog(self).exec()

    def _open_github(self) -> None:
        from app_meta import GITHUB_URL

        QDesktopServices.openUrl(QUrl(GITHUB_URL))

    def _report_issue(self) -> None:
        from app_meta import GITHUB_ISSUES_URL

        QDesktopServices.openUrl(QUrl(GITHUB_ISSUES_URL))

    def _show_mining_page(self) -> None:
        if getattr(self, "_stack", None) is not None and hasattr(self, "_mine_scroll"):
            self._stack.setCurrentWidget(self._mine_scroll)

    def _view_event_logs(self) -> None:
        if hasattr(self, "_mine_tabs") and hasattr(self, "event_log"):
            self._show_mining_page()
            idx = -1
            for i in range(self._mine_tabs.count()):
                if self._mine_tabs.tabText(i).lower().startswith("event"):
                    idx = i
                    break
            if idx >= 0:
                self._mine_tabs.setCurrentIndex(idx)
            self.event_log.setFocus(Qt.FocusReason.OtherFocusReason)

    def _open_connection_settings(self) -> None:
        if hasattr(self, "_mine_tabs"):
            self._show_mining_page()
            idx = -1
            for i in range(self._mine_tabs.count()):
                if "pool" in self._mine_tabs.tabText(i).lower():
                    idx = i
                    break
            if idx >= 0:
                self._mine_tabs.setCurrentIndex(idx)

    def _restart_mining_session(self) -> None:
        from worker.idle_session import IdleSessionState

        if not self.controller.is_running():
            QMessageBox.information(
                self,
                "Restart Mining Session",
                "No mining session is running. Use Start or Start Idle Mode first.",
            )
            return
        was_idle = self._idle_state != IdleSessionState.STOPPED
        reply = QMessageBox.question(
            self,
            "Restart Mining Session",
            "Stop the current session and start again with the same mode?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self._stop_busy:
            return
        self._on_stop()

        def _wait_then_restart() -> None:
            if self._stop_busy or self.controller.is_running():
                QTimer.singleShot(200, _wait_then_restart)
                return
            if was_idle:
                self._on_start_idle()
            else:
                self._on_start()

        QTimer.singleShot(300, _wait_then_restart)

    def _reset_settings(self) -> None:
        from ui.settings_store import DEFAULTS, save_settings

        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Reset machine settings (intensity, thermal, Idle Mode, CPU threads) "
            "to defaults?\n\nPayout addresses and selected network are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        keys = (
            "intensity",
            "pause_temp",
            "resume_temp",
            "cpu_thread_limit",
            "pause_on_battery",
            "allow_mine_without_temp",
            "idle_timeout_s",
            "idle_active_pct",
            "idle_idle_pct",
            "idle_settings_configured",
            "auto_idle_mining",
            "xmrig_donate_level",
            "scoreboard_overlay_enabled",
            "gpu_bus_id",
            "gpu_uuid",
        )
        updates = {k: DEFAULTS[k] for k in keys if k in DEFAULTS}
        updates["gpu_bus_id"] = None
        updates["gpu_uuid"] = None
        updates["idle_settings_configured"] = False
        save_settings(updates)
        self._cfg = load_settings()
        self._push_settings()
        QMessageBox.information(self, "Reset Settings", "Machine settings restored to defaults.")

    def _run_benchmark(self) -> None:
        """Hardware capacity probe (OpenCL / VRAM gates) — useful diagnostics."""
        if self.controller.is_running():
            QMessageBox.warning(
                self,
                "Benchmark",
                "Stop mining before running the hardware capacity benchmark.",
            )
            return
        reply = QMessageBox.question(
            self,
            "Benchmark",
            "Run a hardware capacity check (OpenCL / NVIDIA VRAM gates for "
            "supported networks)?\n\nThis does not measure sustained hashrate.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._on_open_hardware_check()

    def _show_mining_diagnostics(self) -> None:
        from monitor.user_activity import idle_seconds
        from ui.diagnostics_dialog import (
            MiningDiagnosticsDialog,
            build_diagnostics_text,
        )
        from worker.idle_session import IdleSessionState

        text = build_diagnostics_text(
            cfg=self._cfg,
            network_id=self._network_id,
            profile_name=self._profile.display_name,
            engine_kind=self._profile.engine_kind,
            stats=self.controller.stats,
            idle_state=str(
                getattr(self, "_idle_state", IdleSessionState.STOPPED)
            ),
            idle_s=idle_seconds(),
        )
        MiningDiagnosticsDialog(text, self).exec()

    def _show_mining_audit(self) -> None:
        from ui.mining_audit_dialog import MiningAuditDialog

        def _set_live(on: bool) -> None:
            self.controller.set_live_audit(bool(on))
            save_settings({"mining_audit_live_enabled": bool(on)})
            self._cfg["mining_audit_live_enabled"] = bool(on)

        def _set_ledger(on: bool) -> None:
            self.controller.set_work_ledger(bool(on))
            save_settings({"stratum_work_ledger_enabled": bool(on)})
            self._cfg["stratum_work_ledger_enabled"] = bool(on)

        MiningAuditDialog(
            live_enabled=bool(self._cfg.get("mining_audit_live_enabled", False)),
            get_live_snapshot=self.controller.live_audit_snapshot,
            set_live_enabled=_set_live,
            ledger_enabled=bool(self._cfg.get("stratum_work_ledger_enabled", False)),
            get_ledger_metrics=self.controller.work_ledger_metrics,
            get_ledger_export=self.controller.work_ledger_export,
            set_ledger_enabled=_set_ledger,
            parent=self,
        ).exec()

    def _load_capacity_blocks(self) -> dict[str, str]:
        """Restore last successful hardware capacity probe from settings."""
        raw = self._cfg.get("capacity_blocks") or {}
        out: dict[str, str] = {}
        if isinstance(raw, dict):
            for nid, reason in raw.items():
                if reason:
                    out[normalize_network_id(str(nid))] = str(reason)
        return out

    def _persist_capacity_blocks(self, blocks: dict[str, str]) -> None:
        import time

        save_settings(
            {
                "capacity_blocks": dict(blocks),
                "capacity_check_ts": time.time(),
            }
        )
        self._cfg["capacity_blocks"] = dict(blocks)
        self._cfg["capacity_check_ts"] = time.time()

    def _network_blocked_map(self) -> dict[str, str]:
        """Merge light gates + last capacity probe results (persisted)."""
        out: dict[str, str] = {}
        for prof in list_profiles():
            reason = network_block_reason(prof.id, probe_gpu=False)
            if reason:
                out[prof.id] = reason
        for nid, reason in self._capacity_blocks.items():
            if reason:
                out[nid] = reason
        return out

    def _idle_session_active(self) -> bool:
        from worker.idle_session import IdleSessionState

        return getattr(self, "_idle_state", IdleSessionState.STOPPED) != IdleSessionState.STOPPED

    def _apply_idle_mining_ui(self) -> None:
        """Reset mining-page controls (no auto-start)."""
        from worker.idle_session import IdleSessionState

        self._idle_state = IdleSessionState.STOPPED
        self._idle_launching = False
        self._set_session_controls_locked(False)
        self.lbl_conn.setText("Not connected")
        self.lbl_status.setText(
            "Ready — Start for immediate mining, or Start Idle Mode for idle mining."
        )
        self.lbl_rate.setText("0 H/s")
        self._set_activity_ui_waiting("")

    def _position_game_beta_badge(self) -> None:
        """Pin mini BETA chip to the Game Mode button's top-right corner."""
        badge = getattr(self, "_game_beta_badge", None)
        btn = getattr(self, "game_btn", None)
        if badge is None or btn is None:
            return
        badge.adjustSize()
        badge.move(
            max(0, btn.width() - badge.width() - 2),
            2,
        )
        badge.raise_()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is getattr(self, "game_btn", None) and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            self._position_game_beta_badge()
        return super().eventFilter(obj, event)

    def _set_session_controls_locked(self, locked: bool) -> None:
        """Freeze address/network while hashing; allow attaching the other mode."""
        ready = bool(self._profile.mining_ready)
        blocked = bool(network_block_reason(self._network_id, probe_gpu=False))
        running = bool(self.controller.is_running())
        idle_sess = bool(self._idle_session_active())
        native_btc = (
            self._network_id == "btc"
            and self._profile.engine_kind == "native_sha256d"
        )
        auto_on = bool(getattr(self.controller, "is_auto_mode", lambda: False)())
        game_on = bool(getattr(self.controller, "is_game_mode", lambda: False)())
        # Fresh start when idle; or attach Auto while Game-only is live.
        can_start = (
            ready
            and not blocked
            and not idle_sess
            and (
                (not locked and not running)
                or (running and native_btc and game_on and not auto_on)
            )
        )
        # Fresh Game, attach while Auto-only, or reopen board if Game is live.
        scratch_open = self._scratch_window is not None
        can_game = (
            ready
            and not blocked
            and not idle_sess
            and native_btc
            and (
                (not locked and not running)
                or (running and auto_on and not game_on)
                or (running and game_on and not scratch_open)
            )
        )
        self.start_btn.setEnabled(can_start)
        # Idle matches Start for a fresh session; also when Game board is closed
        # but a game-only session is still live (same attach window as Start).
        can_idle = can_start and (
            not running
            or (game_on and not auto_on and not scratch_open)
        )
        self.idle_start_btn.setEnabled(can_idle)
        self.game_btn.setEnabled(can_game)
        self.stop_btn.setEnabled(
            bool(locked) or running or idle_sess
        )
        self.address_edit.setEnabled(not locked and not running)
        self.test_mode.setEnabled(not locked and not running)
        self.btn_change_network.setEnabled(not locked and not running)
        if hasattr(self, "search_strategy"):
            self._refresh_search_strategy_ui()

    def _set_activity_ui_waiting(self, text: str) -> None:
        if hasattr(self, "lbl_activity"):
            self.lbl_activity.setText(text or "—")

    def _idle_active_pct_val(self) -> int:
        raw = self._cfg.get("idle_active_pct")
        if raw is None:
            return 10
        try:
            return max(0, min(100, int(raw)))
        except (TypeError, ValueError):
            return 10

    def _idle_idle_pct_val(self) -> int:
        raw = self._cfg.get("idle_idle_pct")
        if raw is None:
            return 80
        try:
            return max(0, min(100, int(raw)))
        except (TypeError, ValueError):
            return 80

    def _ensure_idle_on_launch(self) -> None:
        """Never resume mining after restart; clear leftover external miners."""
        try:
            from engines.orphan_miners import kill_app_miners

            kill_app_miners()
        except Exception:
            pass
        self._apply_idle_mining_ui()

    def _startup_clear_orphans(self) -> None:
        """Background orphan clear at launch — spinner on network page, no CMD flash."""
        if self._idle_prep_worker is not None and self._idle_prep_worker.isRunning():
            return
        self._select_page.set_busy(
            True, "Starting up… Clearing leftover miners. Please wait."
        )
        worker = _IdlePrepWorker(parent=self)
        self._idle_prep_worker = worker

        def _done() -> None:
            self._select_page.set_busy(False)
            self._apply_idle_mining_ui()
            worker.deleteLater()
            if self._idle_prep_worker is worker:
                self._idle_prep_worker = None

        worker.finished_ok.connect(_done)
        worker.start()

    def _on_open_hardware_check(self) -> None:
        self._stack.setCurrentWidget(self._hw_page)
        # refresh() shows spinner and scans off the UI thread
        self._hw_page.refresh()

    def _on_hardware_back_to_network(self) -> None:
        self._stack.setCurrentWidget(self._select_page)

    def _on_hardware_continue(self) -> None:
        """Stay on hardware page with spinner → capacity probe → network list."""
        from PyQt6.QtCore import QTimer

        from ui.capacity_worker import CapacityProbeWorker

        if self._capacity_worker is not None and self._capacity_worker.isRunning():
            return

        msg = "Checking GPU capacity (OpenCL / NVIDIA VRAM, KawPoW & Autolykos2)…"
        self._hw_page.set_busy(True, msg)

        def _start() -> None:
            worker = CapacityProbeWorker(parent=self)
            self._capacity_worker = worker

            def _ok(blocks: object) -> None:
                mapped: dict[str, str] = {}
                if isinstance(blocks, dict):
                    for k, v in blocks.items():
                        if v:
                            mapped[normalize_network_id(str(k))] = str(v)
                self._capacity_blocks = mapped
                self._persist_capacity_blocks(mapped)
                self._hw_page.set_busy(False)
                self._select_page.apply_blocks(self._network_blocked_map())
                disabled = [k.upper() for k in mapped]
                done = (
                    "Capacity check done. Disabled: " + ", ".join(disabled)
                    if disabled
                    else "Capacity check done — all probed networks look usable."
                )
                self._stack.setCurrentWidget(self._select_page)
                self._select_page.set_busy(False, done)

            def _fail(err: str) -> None:
                self._hw_page.set_busy(False)
                self._select_page.apply_blocks(self._network_blocked_map())
                self._stack.setCurrentWidget(self._select_page)
                self._select_page.set_busy(
                    False,
                    f"Capacity check failed: {err}. Keeping last hardware configuration.",
                )

            worker.finished_ok.connect(_ok)
            worker.failed.connect(_fail)
            worker.start()

        # Let the spinner paint before the worker / GPU probes start
        QTimer.singleShot(40, _start)

    def _check_for_updates(self, *, manual: bool, every_launch: bool = False) -> None:
        import time

        from update.service import should_check_now
        from ui.update_worker import UpdateCheckWorker

        if self._update_check_worker is not None and self._update_check_worker.isRunning():
            if manual:
                QMessageBox.information(self, "Updates", "Update check already running.")
            return

        # every_launch / manual: always hit the network. Background-only path
        # (if ever used) still respects the interval setting.
        if not manual and not every_launch:
            interval = float(self._cfg.get("update_check_interval_hours") or 24.0)
            last = float(self._cfg.get("update_last_check_ts") or 0.0)
            if not should_check_now(last, interval):
                return

        worker = UpdateCheckWorker(force=True, parent=self)
        self._update_check_worker = worker

        def _ok(offer) -> None:
            save_settings({"update_last_check_ts": time.time()})
            self._cfg["update_last_check_ts"] = time.time()
            if offer is None:
                if manual:
                    QMessageBox.information(
                        self,
                        "Updates",
                        "Your application is already up to date.",
                    )
                return
            # "Later" only suppresses until the next app launch (every_launch asks again)
            skipped = str(self._cfg.get("update_skipped_version") or "")
            if (
                not manual
                and not every_launch
                and skipped
                and skipped == offer.remote_version
            ):
                return
            self._prompt_update(offer)

        def _fail(msg: str) -> None:
            save_settings({"update_last_check_ts": time.time()})
            self._cfg["update_last_check_ts"] = time.time()
            if manual:
                QMessageBox.information(
                    self,
                    "Updates",
                    "Could not check for updates right now.\n\n"
                    f"{msg}\n\n"
                    "The app will keep running normally.",
                )

        worker.finished_ok.connect(_ok)
        worker.failed.connect(_fail)
        worker.start()

    def _prompt_update(self, offer) -> None:
        from ui.update_dialog import UpdateAvailableDialog

        dlg = UpdateAvailableDialog(offer, self)
        from PyQt6.QtWidgets import QDialog

        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.choice != "now":
            save_settings({"update_skipped_version": offer.remote_version})
            self._cfg["update_skipped_version"] = offer.remote_version
            return
        self._start_update_download(offer)

    def _start_update_download(self, offer) -> None:
        from ui.update_dialog import UpdateProgressDialog
        from ui.update_worker import UpdatePrepareWorker

        if self._update_prepare_worker is not None and self._update_prepare_worker.isRunning():
            return

        progress = UpdateProgressDialog(self)
        self._update_progress_dlg = progress
        progress.show()

        worker = UpdatePrepareWorker(offer, parent=self)
        self._update_prepare_worker = worker

        def _prog(phase: str, received: int, total) -> None:
            progress.set_phase(phase, received, total)

        def _ok(prepared) -> None:
            progress.set_phase("stop", 0, None)
            self._apply_prepared_update(prepared, progress)

        def _fail(msg: str) -> None:
            progress.close()
            self._update_progress_dlg = None
            QMessageBox.warning(
                self,
                "Update failed",
                f"The update was not installed. Your current version is unchanged.\n\n{msg}",
            )

        worker.progress.connect(_prog)
        worker.finished_ok.connect(_ok)
        worker.failed.connect(_fail)
        worker.start()

    def _apply_prepared_update(self, prepared, progress_dlg) -> None:
        """Stop mining safely, launch external updater, quit."""
        from update.service import UpdateError, launch_external_updater

        self._pending_update = prepared

        def _after_stop(ok: bool) -> None:
            if not ok:
                progress_dlg.close()
                self._update_progress_dlg = None
                self._pending_update = None
                QMessageBox.warning(
                    self,
                    "Update canceled",
                    "Could not stop mining safely. Update was not applied.",
                )
                return
            try:
                progress_dlg.set_phase("apply", 0, None)
                launch_external_updater(prepared)
            except UpdateError as exc:
                progress_dlg.close()
                self._update_progress_dlg = None
                self._pending_update = None
                QMessageBox.warning(self, "Update failed", str(exc))
                return
            progress_dlg.close()
            self._update_progress_dlg = None
            self._tray_exit = True
            self._teardown_for_quit()
            if self.tray is not None:
                self.tray.hide()
            QApplication.instance().quit()

        # Always go through stop path (even if idle) to clear orphans
        if self.controller.is_running() or self._stop_busy:
            self._begin_async_stop(_after_stop)
        else:
            try:
                from engines.orphan_miners import list_app_miners

                orphans = list_app_miners()
            except Exception:
                orphans = []
            if orphans:
                self._begin_async_stop(_after_stop)
            else:
                _after_stop(True)

    def _set_chip(self, chip: QLabel, text: str, *, on: bool) -> None:
        chip.setText(text)
        chip.setObjectName("statusChipOn" if on else "statusChip")
        chip.style().unpolish(chip)
        chip.style().polish(chip)

    def _refresh_header_chips(
        self, *, connected: bool | None = None, conn_txt: str | None = None
    ) -> None:
        if not hasattr(self, "chip_conn"):
            return
        from worker.idle_session import IdleSessionState

        if conn_txt is None:
            conn_txt = self.chip_conn.text() or "Not connected"
        if connected is None:
            connected = conn_txt.lower().startswith("connected") or "test" in conn_txt.lower()
        self._set_chip(self.chip_conn, conn_txt, on=bool(connected))
        idle_on = (
            getattr(self, "_idle_state", IdleSessionState.STOPPED)
            != IdleSessionState.STOPPED
        )
        self._set_chip(
            self.chip_idle,
            "Idle Mode on" if idle_on else "Idle Mode off",
            on=idle_on,
        )

    def _apply_network_to_ui(self) -> None:
        self._profile = get_profile(self._network_id)
        self.setWindowTitle(f"{APP_NAME} — {self._profile.display_name}")
        self._refresh_search_strategy_ui()
        from networks.pool_resolve import resolve_pool

        ep = resolve_pool(self._network_id, self._cfg.get("pool_by_network") or {})
        kind = str(ep.pool_kind or "solo").upper()
        self.lbl_network_badge.setText(
            f"Network: {self._profile.display_name}  ·  {self._profile.algorithm}  ·  "
            f"{ep.host}:{ep.port}  ·  {kind}"
        )
        if hasattr(self, "lbl_sum_network"):
            self.lbl_sum_network.setText(self._profile.display_name)
            self.lbl_sum_algo.setText(self._profile.algorithm)
            self.lbl_sum_pool.setText(f"{ep.host}:{ep.port}")
            self.lbl_sum_mode.setText(kind)
            eng = self._profile.hardware_hint
            if self._profile.engine_kind == "native_sha256d":
                eng_detail = "native engine"
            elif self._network_id == "xmr":
                eng_detail = "XMRig"
            else:
                eng_detail = "managed external"
            self.lbl_sum_engine.setText(
                f"Engine: {eng} · {eng_detail} · {self._profile.pool_fee_note}"
            )
            mode_label = (
                "Solo mining"
                if kind == "SOLO"
                else ("Shared pool" if kind == "SHARED" else f"{kind} mining")
            )
            self._set_chip(self.chip_mode, mode_label, on=(kind == "SOLO"))
        self._refresh_header_chips()
        if hasattr(self, "pool_panel"):
            self.pool_panel.load_network(
                self._network_id, self._cfg.get("pool_by_network") or {}
            )
            self._refresh_pool_banner()
        self.lbl_tagline.setText(
            f"{self._profile.hardware_hint} · no earnings guarantee · "
            f"accepted share ≠ payout · pool: {self._profile.pool_fee_note} · "
            f"engine: {self._profile.engine_fee_note}"
        )
        self.addr_lbl.setText(f"{self._profile.display_name} payout address")
        addrs = self._cfg.get("address_by_network") or {}
        self.address_edit.setText(str(addrs.get(self._network_id) or self._cfg.get("address") or ""))
        ready = self._profile.mining_ready
        # No heavy OpenCL at startup; probe_gpu=True before Start
        blocked = network_block_reason(self._network_id, probe_gpu=False)
        if not self._idle_session_active() and not self.controller.is_running():
            self._set_session_controls_locked(False)
        elif self.controller.is_running() or self._idle_session_active():
            self._set_session_controls_locked(True)
        is_xmr = self._network_id == "xmr"
        is_managed = self._profile.engine_kind == "managed_external"
        self.lbl_total_k.setText("Session attempts")
        self.lbl_lifetime_k.setText("Lifetime attempts")
        from mining.lifetime_stats import get_lifetime_attempts

        if is_xmr:
            # XMRig results.hashes_total → session/lifetime attempts
            self.lbl_total.setText("0")
            self.lbl_lifetime.setText(
                f"{get_lifetime_attempts(self._network_id):,}"
            )
            self.lbl_work.setText(
                "XMRig: attempts from API hashes_total (includes donate window)."
            )
        elif is_managed:
            # Rigel has no reliable cumulative hash counter yet
            self.lbl_total.setText("— (external engine)")
            self.lbl_lifetime.setText("—")
            self.lbl_work.setText(
                "External engine: see hash rate and share rows "
                "(attempt counters: XMRig yes, Rigel not yet)."
            )
        else:
            self.lbl_lifetime.setText(
                f"{get_lifetime_attempts(self._network_id):,}"
            )
        if blocked:
            self.lbl_status.setText(blocked)
        elif not ready:
            self.lbl_status.setText(
                f"{self._profile.display_name} engine is not connected yet — see the note on network selection."
            )
        self._refresh_addr_hint()
        if is_xmr:
            self.lbl_job_k.setText("Current work (height/diff)")
        elif self._network_id == "bch":
            self.lbl_job_k.setText("Current job ID")
        else:
            self.lbl_job_k.setText("Current job ID")
        self._refresh_stats_link_ui()

    def _on_network_chosen(self, network_id: str) -> None:
        """Continue → show circle spinner, clear orphans in background, then mining UI."""
        if self._idle_prep_worker is not None and self._idle_prep_worker.isRunning():
            return

        self._select_page.set_busy(
            True,
            "Preparing mining screen… Clearing leftover miners. Please wait.",
        )

        def _start_prep() -> None:
            worker = _IdlePrepWorker(parent=self)
            self._idle_prep_worker = worker

            def _done() -> None:
                try:
                    if not self._switch_network(network_id):
                        return
                    self._apply_idle_mining_ui()
                    self._stack.setCurrentWidget(self._mine_scroll)
                finally:
                    self._select_page.set_busy(False)
                    worker.deleteLater()
                    if self._idle_prep_worker is worker:
                        self._idle_prep_worker = None

            worker.finished_ok.connect(_done)
            worker.start()

        # Paint spinner before PowerShell / orphan scan starts
        QTimer.singleShot(40, _start_prep)

    def _on_pick_gpu(self) -> None:
        try:
            from monitor.gpu_devices import list_gpus, list_nvidia_only

            # RVN/ERG (Rigel) are CUDA-only; BTC/BCH accept any OpenCL vendor
            if self._network_id in ("rvn", "erg"):
                devices = list_nvidia_only()
            else:
                devices = list_gpus()
        except Exception as exc:
            QMessageBox.warning(self, "GPU list", str(exc))
            return
        if not devices:
            msg = (
                "No NVIDIA GPU found (required for RVN/ERG)."
                if self._network_id in ("rvn", "erg")
                else "No OpenCL GPU found (NVIDIA / AMD / Intel)."
            )
            QMessageBox.warning(self, "GPU list", msg)
            return
        lines = [
            f"{i}: [{d.vendor}] {d.name} bus={d.bus_id} "
            f"free={d.free_vram_mb}MB/{d.total_vram_mb}MB"
            for i, d in enumerate(devices)
        ]
        # Simple pick: auto-save single GPU; multi-GPU uses dialog
        if len(devices) == 1:
            d = devices[0]
            save_settings({"gpu_bus_id": d.bus_id, "gpu_uuid": d.uuid})
            self._cfg = load_settings()
            self._apply_network_to_ui()
            QMessageBox.information(
                self,
                "GPU",
                f"Selected (single GPU):\n[{d.vendor}] {d.name}\n"
                f"bus={d.bus_id}\nfree={d.free_vram_mb}MB",
            )
            return
        # Multi-GPU: list for user; dialog instead of defaulting to first card
        from PyQt6.QtWidgets import QInputDialog

        choice, ok = QInputDialog.getItem(
            self,
            "Pick GPU",
            "Card to match by PCI bus / UUID (NVIDIA / AMD / Intel):",
            lines,
            0,
            False,
        )
        if not ok:
            return
        idx = lines.index(choice)
        d = devices[idx]
        save_settings({"gpu_bus_id": d.bus_id, "gpu_uuid": d.uuid})
        self._cfg = load_settings()
        self._apply_network_to_ui()

    def _on_change_network(self) -> None:
        if not self._ensure_stopped_for_network_switch():
            return
        # Keep last capacity_blocks (persisted) — do not re-enable disabled nets
        self._select_page.apply_blocks(self._network_blocked_map())
        self._stack.setCurrentWidget(self._select_page)

    def _set_stop_busy_ui(self, busy: bool) -> None:
        self._stop_busy = busy
        if busy:
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.btn_change_network.setEnabled(False)
            self.controller.stats.status = "Stopping…"
            self._apply_stats(self.controller.stats)
        else:
            # keep network switch disabled while stop_failed
            if not self.controller._stop_failed:
                self.btn_change_network.setEnabled(True)

    def _begin_async_stop(self, on_done) -> None:
        """Stop without blocking the UI thread; on_done(ok) when finished."""
        if self._stop_busy:
            return
        if self._stop_worker is not None and self._stop_worker.isRunning():
            return
        self._set_stop_busy_ui(True)
        worker = _StopWorker(self.controller)
        self._stop_worker = worker

        def _finished(ok: bool) -> None:
            self._force_stop_all_miners()
            self._set_stop_busy_ui(False)
            on_done(bool(ok))
            worker.deleteLater()
            if self._stop_worker is worker:
                self._stop_worker = None

        worker.finished_ok.connect(_finished)
        worker.start()

    def _ensure_stopped_for_network_switch(self) -> bool:
        """Network cannot change until stop completes. Starts async stop if running (returns False)."""
        if self._stop_busy:
            QMessageBox.information(
                self, "Stopping", "Cannot change network until stop finishes."
            )
            return False
        if not self.controller.is_running():
            return True

        def _after(ok: bool) -> None:
            if not ok or self.controller.is_running():
                QMessageBox.warning(
                    self,
                    "Could not stop",
                    "Previous mining session has not closed yet. New network was not started.",
                )
                self.stop_btn.setEnabled(True)
                self.start_btn.setEnabled(False)
                return
            self.start_btn.setEnabled(self._profile.mining_ready)
            self.stop_btn.setEnabled(False)
            self.address_edit.setEnabled(True)
            self.test_mode.setEnabled(True)
            self._on_change_network()

        self._begin_async_stop(_after)
        return False

    def _switch_network(self, network_id: str) -> bool:
        if not self._ensure_stopped_for_network_switch():
            return False
        self._persist_form()
        self._network_id = normalize_network_id(network_id)
        self._cfg["selected_network"] = self._network_id
        save_settings({"selected_network": self._network_id})
        self._cfg = load_settings()
        self._apply_network_to_ui()
        self._load_stored_best_into_row()
        return True

    def _open_ckpool_stats(self) -> None:
        url = getattr(self, "_stats_url", "") or ""
        if not url:
            return
        # safe open for bitcoincash: in path
        q = QUrl.fromUserInput(url)
        if not q.isValid():
            q = QUrl(url)
        QDesktopServices.openUrl(q)

    def _on_address_changed(self, _text: str) -> None:
        self._refresh_addr_hint()
        self._addr_save_timer.start(600)

    def _refresh_addr_hint(self) -> None:
        text = self.address_edit.text().strip()
        if not text:
            self._addr_hint.setText("Address empty — enter before Start; it will be saved.")
            return
        self._addr_hint.setText("Saved / will save (no need to re-enter each time).")

    def _on_donate(self) -> None:
        DonateDialog(self).exec()

    def _clamp_window_to_screen(
        self, *, preferred_w: int | None = None, preferred_h: int | None = None
    ) -> None:
        """
        Initial/preferred resize within the available desktop.
        Do NOT setMaximumSize to the screen — that greys out the title-bar
        maximize button on Windows when max == work-area size.
        """
        # Keep maximize enabled (□).
        self.setMaximumSize(16777215, 16777215)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            if preferred_w is not None and preferred_h is not None:
                self.resize(preferred_w, preferred_h)
            return
        if self.isMaximized() or self.isFullScreen():
            return
        avail = screen.availableGeometry()
        fit_w = max(self.minimumWidth(), avail.width())
        fit_h = max(self.minimumHeight(), avail.height())
        w = preferred_w if preferred_w is not None else self.width()
        h = preferred_h if preferred_h is not None else self.height()
        self.resize(
            min(max(self.minimumWidth(), w), fit_w),
            min(max(self.minimumHeight(), h), fit_h),
        )

    def _current_tab_scroll(self) -> QScrollArea | None:
        if not hasattr(self, "_mine_tabs"):
            return None
        w = self._mine_tabs.currentWidget()
        return w if isinstance(w, QScrollArea) else None

    @contextmanager
    def _hold_mine_scroll(self) -> Iterator[None]:
        """Keep the active tab scroll still while focus/enable changes (Start/Stop)."""
        sa = self._current_tab_scroll()
        if sa is None:
            yield
            return
        bar = sa.verticalScrollBar()
        hbar = sa.horizontalScrollBar()
        vpos, hpos = bar.value(), hbar.value()

        def _restore() -> None:
            bar.setValue(vpos)
            hbar.setValue(hpos)

        try:
            yield
        finally:
            _restore()
            QTimer.singleShot(0, _restore)

    def _on_pool_applied(self, pool_by_network: dict) -> None:
        save_settings({"pool_by_network": pool_by_network})
        self._cfg = load_settings()
        self._refresh_pool_banner()
        if not self.controller.is_running():
            self._refresh_stats_link_ui()

    def _current_pool_stats_url(self, address: str | None = None) -> str:
        from networks.pool_resolve import resolve_pool, stats_url_for_endpoint

        addr = (
            self.address_edit.text().strip()
            if address is None
            else (address or "").strip()
        )
        ep = resolve_pool(self._network_id, self._cfg.get("pool_by_network") or {})
        return stats_url_for_endpoint(ep, addr)

    def _stats_link_caption(self, url: str) -> str:
        low = (url or "").lower()
        if "kryptex.com" in low:
            return f"Rewards / account (Kryptex; accepted≠block): {url}"
        if "2miners.com" in low:
            return f"Account page (2Miners; accepted≠block): {url}"
        if "ckpool.org" in low:
            return f"Pool stats (CKPool): {url}"
        return f"Pool rewards / stats: {url}"

    def _refresh_stats_link_ui(self, url: str | None = None) -> None:
        """Bind Status rewards button to the *selected* pool; hide when unknown."""
        from networks.pool_resolve import resolve_pool

        preview = url if url is not None else self._current_pool_stats_url()
        ep = resolve_pool(self._network_id, self._cfg.get("pool_by_network") or {})
        is_xmr = self._network_id == "xmr"
        if preview:
            self.lbl_stats_url.setText(self._stats_link_caption(preview))
            if is_xmr or "kryptex.com" in preview.lower() or "2miners.com" in preview.lower():
                self.btn_stats.setText("Open rewards page")
            else:
                self.btn_stats.setText("Open pool page")
            self.btn_stats.setEnabled(True)
            self._stats_url = preview
        else:
            if ep.mode == "custom":
                self.lbl_stats_url.setText(
                    "No rewards/account page for this custom pool — "
                    "check the pool website manually (accepted ≠ block)."
                )
            elif not self.address_edit.text().strip():
                self.lbl_stats_url.setText(
                    "Rewards / account: enter a wallet address when this pool provides a stats page."
                )
            else:
                self.lbl_stats_url.setText(
                    "No rewards/account page configured for the selected pool."
                )
            self.btn_stats.setText("Open pool page")
            self.btn_stats.setEnabled(False)
            self._stats_url = ""

        if is_xmr:
            if preview and "kryptex.com" in preview.lower():
                self.lbl_stats_hint.setText(
                    "Open the Kryptex rewards page (accepted = share, not a block). "
                    "Work row shows height/diff from XMRig; no stratum job_id."
                )
            elif preview:
                self.lbl_stats_hint.setText(
                    "Open this pool’s rewards/account page (accepted = share, not a block). "
                    "Work row shows height/diff from XMRig; no stratum job_id."
                )
            else:
                self.lbl_stats_hint.setText(
                    "This pool has no in-app rewards link. Check the pool site manually "
                    "(accepted = share, not a block). Work row shows height/diff from XMRig."
                )
        elif self._network_id == "bch":
            self.btn_stats.setText(
                "Open account page" if preview else "Open pool page"
            )
            self.lbl_stats_hint.setText(
                "2Miners home page does not list you; you need /account/bitcoincash:…. "
                "Without a first accepted share the site shows /search (mindiff ~32K — can take a while on GPU)."
                if preview and "2miners.com" in preview.lower()
                else (
                    "Use the pool account/stats page when available. "
                    "Accepted shares are not block rewards."
                )
            )
        else:
            self.lbl_stats_hint.setText(
                "Server stats may lag; with low hash rate / high mindiff they "
                "may not show up immediately."
                if preview
                else "No pool stats page for this selection — check the pool website if needed."
            )
        hint = (self.lbl_stats_hint.text() or "").strip()
        self.lbl_stats_hint.setVisible(bool(hint))

    def _refresh_pool_banner(self) -> None:
        from networks.pool_resolve import resolve_pool
        from networks.pool_validation import get_validation_profile

        ep = resolve_pool(self._network_id, self._cfg.get("pool_by_network") or {})
        vp = get_validation_profile(ep.validation_profile_id)
        text = ""
        if ep.pool_kind == "shared":
            text = vp.banner_text or (
                "SHARED pool — do not expect a full solo block reward."
            )
        elif vp.payout_unverified_banner and vp.banner_text:
            text = vp.banner_text
        elif ep.mode != "default" and ep.pool_kind == "unknown":
            text = get_validation_profile("unknown_custom").banner_text
        if text:
            self.lbl_pool_banner.setText(text)
            self.lbl_pool_banner.setVisible(True)
        else:
            self.lbl_pool_banner.setVisible(False)

    def _persist_form(self) -> None:
        addr = self.address_edit.text().strip()
        by_net = dict(self._cfg.get("address_by_network") or {})
        by_net[self._network_id] = addr
        save_settings(
            {
                "selected_network": self._network_id,
                "address": addr,
                "address_by_network": by_net,
                "intensity": int(self._cfg.get("intensity") or 4),
                "pause_temp": int(self._cfg.get("pause_temp") or 75),
                "resume_temp": int(self._cfg.get("resume_temp") or 60),
                "test_mode": self.test_mode.isChecked(),
                "cpu_thread_limit": int(self._cfg.get("cpu_thread_limit") or 0),
                "pause_on_battery": bool(self._cfg.get("pause_on_battery", True)),
                "allow_mine_without_temp": bool(
                    self._cfg.get("allow_mine_without_temp", False)
                ),
                "miner_download_consent": bool(
                    self._cfg.get("miner_download_consent", False)
                ),
                "gpu_bus_id": self._cfg.get("gpu_bus_id"),
                "gpu_uuid": self._cfg.get("gpu_uuid"),
                "window_width": self.width(),
                "window_height": self.height(),
                "scoreboard_overlay_enabled": bool(
                    self._cfg.get("scoreboard_overlay_enabled", True)
                ),
                "setup_wizard_done": bool(self._cfg.get("setup_wizard_done", False)),
                "pool_by_network": self._cfg.get("pool_by_network") or {},
                "mining_search_strategy": str(
                    self.search_strategy.currentData()
                    or self._cfg.get("mining_search_strategy")
                    or "sequential"
                ),
            }
        )
        self._cfg = load_settings()
        self._refresh_addr_hint()
        if not self.controller.is_running():
            self._refresh_stats_link_ui()

    def _on_search_strategy_changed(self, *_args) -> None:
        if self.controller.is_running() or self._idle_session_active():
            # Revert combo to locked session strategy
            cur = self.controller.search_strategy()
            i = self.search_strategy.findData(cur)
            if i >= 0:
                self.search_strategy.blockSignals(True)
                self.search_strategy.setCurrentIndex(i)
                self.search_strategy.blockSignals(False)
            return
        self.controller.set_search_strategy(str(self.search_strategy.currentData() or "sequential"))
        self._persist_form()

    def _refresh_search_strategy_ui(self) -> None:
        native = self._profile.engine_kind == "native_sha256d"
        for w in (self.lbl_search_strategy, self.search_strategy):
            w.setVisible(native)
        self.lbl_search_strategy_hint.setVisible(False)
        locked = self.controller.is_running() or self._idle_session_active()
        self.search_strategy.setEnabled(native and not locked)
        if native and not locked:
            raw = str(self._cfg.get("mining_search_strategy") or "sequential").lower()
            i = self.search_strategy.findData(raw)
            if i >= 0 and self.search_strategy.currentIndex() != i:
                self.search_strategy.blockSignals(True)
                self.search_strategy.setCurrentIndex(i)
                self.search_strategy.blockSignals(False)
            self.controller.set_search_strategy(raw)

    def _intensity_val(self) -> int:
        return int(self._cfg.get("intensity") or 4)

    def _pause_temp_val(self) -> int:
        return int(self._cfg.get("pause_temp") or 75)

    def _resume_temp_val(self) -> int:
        return int(self._cfg.get("resume_temp") or 60)

    def _cpu_threads_val(self) -> int:
        return int(self._cfg.get("cpu_thread_limit") or 0)

    def _pause_battery_val(self) -> bool:
        return bool(self._cfg.get("pause_on_battery", True))

    def _push_settings(self) -> None:
        import time as _time

        from worker.idle_session import (
            IdleSessionState,
            promote_after_miner_start,
            should_enable_idle_policy,
        )

        now = _time.time()
        last = getattr(self, "_idle_wall_watch", None)
        self._idle_wall_watch = now
        state = getattr(self, "_idle_state", IdleSessionState.STOPPED)
        running = self.controller.is_running()
        # Recover WAITING→MINING_IDLE if miner already up (state/policy race).
        if state == IdleSessionState.WAITING_FOR_IDLE and running:
            from monitor.user_activity import idle_seconds

            self._idle_state = promote_after_miner_start(
                state,
                idle_s=idle_seconds(),
                timeout_s=int(self._cfg.get("idle_timeout_s") or 150),
            )
            state = self._idle_state
        policy_on = should_enable_idle_policy(state, miner_running=running)
        # Sleep/hibernate: wall clock jumped while our 1s timer was suspended.
        if last is not None and (now - last) >= 5.0 and policy_on and running:
            self.controller.force_idle_active()

        self.controller.update_settings(
            self._intensity_val(),
            self._pause_temp_val(),
            self._resume_temp_val(),
        )
        # WAITING (no miner): policy off. After miner start: policy on so ACTIVE pauses/scales.
        self.controller.update_idle_options(
            enabled=policy_on,
            timeout_s=int(self._cfg.get("idle_timeout_s") or 150),
            active_pct=self._idle_active_pct_val(),
            idle_pct=self._idle_idle_pct_val(),
        )
        self._tick_idle_session()
        self._poll_temperature_always()

    def _allow_mine_without_temp(self) -> bool:
        # Thermal protection is mandatory — override is never honored.
        return False

    def _poll_temperature_always(self) -> None:
        """Temperature runs even when idle; updates HUD without a mining session."""
        try:
            self.controller.gpu_bus_id = str(self._cfg.get("gpu_bus_id") or "")
            self.controller.gpu_uuid = str(self._cfg.get("gpu_uuid") or "")
            if not self.controller.is_running():
                self.controller.network_id = self._network_id
                self.controller.poll_temperature()
            stats = self.controller.stats
            if stats.temp_readable and stats.gpu_temp is not None:
                extra = " · paused" if stats.paused_thermal else ""
                self.lbl_temp.setText(f"{stats.gpu_temp}°C{extra}")
                self._update_scoreboard_temp(int(stats.gpu_temp))
                self._refresh_thermal_unsafe_banner(running_without_temp=False)
            elif not self.controller.is_running():
                self.lbl_temp.setText("unreadable · mining blocked until fixed")
                self._update_scoreboard_temp(None)
                self._refresh_thermal_unsafe_banner(running_without_temp=False)
            if getattr(stats, "thermal_source", ""):
                self.lbl_thermal_src.setText(
                    f"Temperature source: {stats.thermal_source}"
                )
        except Exception:
            pass

    def _miner_consent_ok(self) -> bool:
        return bool(self._cfg.get("miner_download_consent", False))

    def _refresh_thermal_unsafe_banner(self, *, running_without_temp: bool = False) -> None:
        if self._allow_mine_without_temp() or running_without_temp:
            self.lbl_thermal_unsafe.setText(
                "UNSAFE: automatic thermal protection is off — monitor GPU/CPU heat manually."
            )
            self.lbl_thermal_unsafe.setVisible(True)
        else:
            self.lbl_thermal_unsafe.setText("")
            self.lbl_thermal_unsafe.setVisible(False)

    def _confirm_mine_without_temp(self, detail: str) -> bool:
        """
        Temp unreadable and override off.
        Popup liability disclaimer; Continues only after explicit acknowledgement.
        """
        from ui.thermal_disclaimer_dialog import (
            ThermalDisclaimerDialog,
            ask_thermal_disclaimer,
        )

        choice = ask_thermal_disclaimer(self, detail)
        if choice == ThermalDisclaimerDialog.RESULT_ALWAYS:
            save_settings({"allow_mine_without_temp": True})
            self._cfg["allow_mine_without_temp"] = True
            self._refresh_thermal_unsafe_banner()
            return True
        if choice == ThermalDisclaimerDialog.RESULT_ONCE:
            return True
        return False

    def _maybe_offer_missing_miners(self) -> None:
        """First window show: offer XMRig/Rigel download if not installed (pre-selected)."""
        if bool(self._cfg.get("miner_startup_offer_done", False)):
            return
        from engines.miner_catalog import list_missing_miners, save_consent
        from ui.miner_consent_dialog import ask_startup_miner_download

        missing = list_missing_miners()
        if not missing:
            save_settings({"miner_startup_offer_done": True})
            self._cfg["miner_startup_offer_done"] = True
            return

        selected = ask_startup_miner_download(self, missing)
        save_settings({"miner_startup_offer_done": True})
        self._cfg["miner_startup_offer_done"] = True
        if selected is None:
            return
        if not selected:
            return

        save_consent(True)
        self._cfg["miner_download_consent"] = True
        self._download_miners_with_ui(selected)

    def _download_miners_with_ui(
        self,
        miner_ids: list[str],
        *,
        on_success=None,
    ) -> None:
        """
        Download + verify with a progress dialog (background thread).
        on_success() is called after the dialog closes on success (optional).
        """
        from engines.miner_catalog import get_miner_info
        from engines.windows_security import looks_like_defender_block
        from ui.defender_help_dialog import show_defender_help
        from ui.miner_download_dialog import MinerDownloadProgressDialog
        from ui.miner_download_worker import MinerDownloadWorker

        if not miner_ids:
            if on_success:
                on_success()
            return

        if self._miner_dl_worker is not None and self._miner_dl_worker.isRunning():
            QMessageBox.information(
                self, "Download in progress", "A miner download is already running."
            )
            return

        self._after_miner_download = on_success
        dlg = MinerDownloadProgressDialog(parent=self)
        self._miner_dl_dialog = dlg
        worker = MinerDownloadWorker(miner_ids, parent=self)
        self._miner_dl_worker = worker
        _fail_name = {"id": ""}

        def _started(mid: str, index: int, total: int) -> None:
            try:
                name = get_miner_info(mid).display_name
            except Exception:
                name = mid
            _fail_name["id"] = name
            dlg.set_miner_title(name, index, total)
            dlg.append_log(f"—— {name} ——")

        def _prog(_mid: str, phase: str, received: int, total, detail: str) -> None:
            dlg.set_progress(phase, received, total, detail)

        def _ok() -> None:
            dlg.mark_success("All selected miners downloaded and verified.")

        def _fail(mid: str, message: str) -> None:
            try:
                name = get_miner_info(mid).display_name
            except Exception:
                name = mid
            _fail_name["id"] = name
            detail = (
                f"Could not download or verify {name}.\n\n{message}\n\n"
                "Your previous install (if any) was left unchanged. "
                "This app does not disable Windows Defender."
            )
            dlg.mark_error(detail)

        worker.miner_started.connect(_started)
        worker.progress.connect(_prog)
        worker.finished_ok.connect(_ok)
        worker.failed.connect(_fail)
        worker.start()
        dlg.exec()
        self._miner_dl_dialog = None
        failed = dlg.failed
        cb = self._after_miner_download
        self._after_miner_download = None
        if failed:
            if looks_like_defender_block(RuntimeError(dlg.log.toPlainText())):
                show_defender_help(self, _fail_name["id"] or "miner")
            return
        # After first-run miner install, refresh detection on the hardware page
        if self._stack.currentWidget() is self._hw_page:
            self._hw_page.refresh()
        if cb:
            cb()

    def _ensure_external_miner_ready(self, *, on_ready=None) -> bool:
        """
        Consent + download only the miner required for the current network.
        Returns True if already ready. Returns False if declined or download started
        (on_ready called after a successful download).
        """
        # BTC/BCH native OpenCL — never touch miners.lock.json
        if getattr(self._profile, "engine_kind", "") != "managed_external":
            return True

        from engines.miner_catalog import (
            is_miner_installed,
            miner_id_for_network,
            save_consent,
        )
        from ui.miner_consent_dialog import ask_miner_download_consent

        miner_id = miner_id_for_network(self._network_id)
        if not miner_id:
            return True  # no catalog entry — treat as ready / native

        if is_miner_installed(miner_id) and self._miner_consent_ok():
            return True

        if not self._miner_consent_ok():
            if not ask_miner_download_consent(self, [miner_id]):
                QMessageBox.information(
                    self,
                    "Download declined",
                    "Mining with this network needs an official miner download. "
                    "You can accept the download prompt when you Start again.",
                )
                return False
            save_consent(True)
            self._cfg["miner_download_consent"] = True
            self._persist_form()

        if is_miner_installed(miner_id):
            return True

        self._download_miners_with_ui([miner_id], on_success=on_ready)
        return False

    def _on_start(self) -> None:
        try:
            from worker.idle_session import IdleSessionState

            self._idle_state = IdleSessionState.STOPPED
            self._idle_launching = False
            self._pending_session_kind = "auto"
            self._on_start_inner()
        except Exception as exc:
            import traceback

            traceback.print_exc()
            QMessageBox.warning(
                self,
                "Could not start",
                f"Start failed unexpectedly:\n\n{exc}",
            )

    def _on_start_game(self) -> None:
        """Mandatory consent each entry → Game Mode session (BTC native only)."""
        from worker.idle_session import IdleSessionState

        if self._network_id != "btc" or self._profile.engine_kind != "native_sha256d":
            QMessageBox.information(
                self,
                "Game Mode",
                "Scratch Mining Game Mode is available on BTC (native OpenCL) only.",
            )
            return
        # Reopen board UI if Game session is already live (window was closed).
        if (
            self.controller.is_running()
            and self.controller.is_game_mode()
            and self._scratch_window is None
        ):
            self._show_game_busy("Opening Game Mode…")
            try:
                self._open_scratch_window()
                self._set_session_controls_locked(True)
            finally:
                self._hide_game_busy()
            return
        from ui.scratch_game_dialog import ScratchGameConsentDialog

        dlg = ScratchGameConsentDialog(self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self._idle_state = IdleSessionState.STOPPED
        self._idle_launching = False
        self._pending_session_kind = "game"
        self._persist_form()
        self._push_settings()
        if not self._preflight_can_mine():
            self._pending_session_kind = "auto"
            return
        self._show_game_busy("Opening Game Mode…")
        try:
            self._begin_mining_after_gates()
        finally:
            self._hide_game_busy()

    def _idle_settings_ready(self) -> bool:
        return bool(self._cfg.get("idle_settings_configured", False)) or bool(
            self._cfg.get("auto_idle_mining", False)
        )

    def _on_start_idle(self) -> None:
        """
        STOPPED → mining now at While-using-PC intensity (not a silent wait).
        After AFK timeout → While-AFK intensity; input → Using-PC intensity again.
        """
        from monitor.user_activity import idle_seconds
        from worker.idle_session import (
            IdleSessionState,
            initial_mining_state_from_activity,
        )

        if not self._idle_settings_ready():
            QMessageBox.warning(
                self,
                "Idle Mode settings required",
                "Configure Idle Mode under Settings first (AFK timeout and "
                "While-using-PC / While-AFK intensity), then save. "
                "The session will not start until settings are saved.",
            )
            self._open_settings(focus_idle=True)
            return
        if not self._preflight_can_mine():
            return
        self._persist_form()
        timeout = int(self._cfg.get("idle_timeout_s") or 150)
        active_pct = self._idle_active_pct_val()
        idle_pct = self._idle_idle_pct_val()
        # Target state from current activity; mining starts immediately.
        self._idle_state = initial_mining_state_from_activity(
            idle_s=idle_seconds(), timeout_s=timeout
        )
        self._idle_launching = False
        self.controller.update_idle_options(
            enabled=True,
            timeout_s=timeout,
            active_pct=active_pct,
            idle_pct=idle_pct,
            arm_session=True,
        )
        self._idle_state = IdleSessionState.MINING_ACTIVE
        with self._hold_mine_scroll():
            self.stop_btn.setEnabled(True)
            self.idle_start_btn.clearFocus()
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self._set_session_controls_locked(True)
        self.lbl_status.setText(
            f"Idle Mode — starting at While-using-PC intensity ({active_pct}%)."
        )
        self._set_activity_ui_waiting("Using PC · starting")
        self._refresh_header_chips()
        self._launch_idle_mining()

    def _tick_idle_session(self) -> None:
        """Sync MINING_IDLE ↔ MINING_ACTIVE from policy while Start Idle runs."""
        from worker.idle_session import (
            IdleSessionState,
            mining_state_from_policy_mode,
            promote_after_miner_start,
        )

        state = getattr(self, "_idle_state", IdleSessionState.STOPPED)
        if state == IdleSessionState.STOPPED:
            return

        timeout = int(self._cfg.get("idle_timeout_s") or 150)

        if state == IdleSessionState.WAITING_FOR_IDLE and self.controller.is_running():
            from monitor.user_activity import idle_seconds

            self._idle_state = promote_after_miner_start(
                state, idle_s=idle_seconds(), timeout_s=timeout
            )
            self.controller.update_idle_options(
                enabled=True,
                timeout_s=timeout,
                active_pct=self._idle_active_pct_val(),
                idle_pct=self._idle_idle_pct_val(),
            )
            return

        if state in (IdleSessionState.MINING_IDLE, IdleSessionState.MINING_ACTIVE):
            if not self.controller.is_running():
                return
            mode = str(getattr(self.controller.stats, "activity_mode", "") or "")
            if mode in ("idle", "active"):
                self._idle_state = mining_state_from_policy_mode(mode)

    def _launch_idle_mining(self) -> None:
        self._pending_session_kind = "auto"
        """Start miner for Start Idle (Using-PC intensity from the first moment)."""
        from worker.idle_session import IdleSessionState

        if self._idle_state == IdleSessionState.STOPPED:
            return
        if self._idle_launching or self.controller.is_running():
            return

        def _launch() -> None:
            try:
                if self._idle_state == IdleSessionState.STOPPED:
                    return
                if not self._preflight_can_mine():
                    self._stop_idle_session_to_stopped()
                    return
                timeout = int(self._cfg.get("idle_timeout_s") or 150)
                self.controller.update_idle_options(
                    enabled=True,
                    timeout_s=timeout,
                    active_pct=self._idle_active_pct_val(),
                    idle_pct=self._idle_idle_pct_val(),
                    arm_session=True,
                )
                self._begin_mining_after_gates()
                self._idle_state = IdleSessionState.MINING_ACTIVE
                self.controller.update_idle_options(
                    enabled=True,
                    timeout_s=timeout,
                    active_pct=self._idle_active_pct_val(),
                    idle_pct=self._idle_idle_pct_val(),
                    arm_session=True,
                )
            finally:
                self._idle_launching = False

        self._idle_launching = True
        if self._ensure_external_miner_ready(on_ready=_launch):
            _launch()
            return
        dl = getattr(self, "_miner_dl_worker", None)
        if dl is None or not dl.isRunning():
            self._idle_launching = False
            self._stop_idle_session_to_stopped()
            self.lbl_status.setText("Idle Mode — miner not ready.")

    def _preflight_can_mine(self) -> bool:
        blocked = network_block_reason(self._network_id, probe_gpu=True)
        if blocked:
            QMessageBox.warning(self, "Hardware / dependency", blocked)
            return False
        if not self._profile.mining_ready:
            QMessageBox.information(
                self,
                "No engine",
                f"{self._profile.display_name} mining engine is not connected yet.\n"
                f"{self._profile.notes}",
            )
            return False
        if self._profile.engine_kind == "managed_external" and self._network_id not in (
            "xmr",
            "rvn",
            "erg",
        ):
            QMessageBox.information(
                self,
                "Managed engine",
                f"{self._profile.display_name} will connect in a later release.",
            )
            return False
        if self._stop_busy:
            QMessageBox.information(
                self, "Stopping", "Cannot start a new session until stop finishes."
            )
            return False
        return True

    def _on_start_inner(self) -> None:
        self._persist_form()
        self._push_settings()
        if not self._preflight_can_mine():
            return

        if not self._ensure_external_miner_ready(on_ready=self._begin_mining_after_gates):
            return

        self._begin_mining_after_gates()

    def _begin_mining_after_gates(self) -> None:
        """Thermal gate + controller.start (after miner is ready)."""
        from worker.idle_session import IdleSessionState

        self._defender_help_shown = False

        from monitor.thermal_probe import probe_temperature_readable

        temp_ok, temp_detail = probe_temperature_readable(
            self._network_id,
            gpu_bus_id=str(self._cfg.get("gpu_bus_id") or ""),
            gpu_uuid=str(self._cfg.get("gpu_uuid") or ""),
        )
        if not temp_ok:
            self._refresh_thermal_unsafe_banner(running_without_temp=False)
            QMessageBox.warning(
                self,
                "Temperature required",
                "Mining cannot start without a readable temperature sensor.\n\n"
                f"{temp_detail}\n\n"
                "Thermal protection is mandatory: fix NVML/CPU sensors, then try again.",
            )
            if (
                self._idle_state == IdleSessionState.WAITING_FOR_IDLE
                and not self.controller.is_running()
            ):
                self.lbl_status.setText(
                    "Waiting for system idle... (thermal gate blocked — still monitoring)"
                )
            return

        try:
            if self._profile.engine_kind == "native_sha256d":
                self.controller.set_search_strategy(
                    str(self.search_strategy.currentData() or "sequential")
                )
            else:
                self.controller.set_search_strategy("sequential")
            self._refresh_search_strategy_ui()
            self.controller.update_cpu_options(
                cpu_thread_limit=self._cpu_threads_val(),
                pause_on_battery=self._pause_battery_val(),
                xmrig_donate_level=int(self._cfg.get("xmrig_donate_level") or 1),
            )
            self.controller.gpu_bus_id = str(self._cfg.get("gpu_bus_id") or "")
            self.controller.gpu_uuid = str(self._cfg.get("gpu_uuid") or "")
            from worker.idle_session import (
                IdleSessionState,
                should_enable_idle_policy,
            )

            # Enable policy once this Start Idle session is about to mine.
            # Game Mode never arms idle hashing.
            session_kind = str(self._pending_session_kind or "auto")
            arm_idle = (
                self._idle_state != IdleSessionState.STOPPED
                and session_kind != "game"
            )
            to = int(self._cfg.get("idle_timeout_s") or 150)
            self.controller.update_idle_options(
                enabled=arm_idle,
                timeout_s=to,
                active_pct=self._idle_active_pct_val(),
                idle_pct=self._idle_idle_pct_val(),
                arm_session=arm_idle,
            )
            self.controller.start(
                self.address_edit.text(),
                test_mode=self.test_mode.isChecked(),
                network_id=self._network_id,
                allow_mine_without_temp=False,
                pool_by_network=self._cfg.get("pool_by_network") or {},
                session_kind=session_kind,
            )
            if session_kind == "game":
                self._open_scratch_window()
            self._pending_session_kind = "auto"
            if arm_idle:
                # Keep Using-PC intensity at session start (do not jump to AFK %).
                self._idle_state = IdleSessionState.MINING_ACTIVE
                if should_enable_idle_policy(
                    self._idle_state, miner_running=True
                ):
                    self.controller.update_idle_options(
                        enabled=True,
                        timeout_s=to,
                        active_pct=self._idle_active_pct_val(),
                        idle_pct=self._idle_idle_pct_val(),
                        arm_session=True,
                    )
        except Exception as exc:
            self._pending_session_kind = "auto"
            from engines.windows_security import looks_like_defender_block
            from ui.defender_help_dialog import show_defender_help

            if looks_like_defender_block(exc):
                label = "XMRig" if self._network_id == "xmr" else "Rigel"
                show_defender_help(self, label)
            else:
                QMessageBox.warning(self, "Could not start", str(exc))
            return
        with self._hold_mine_scroll():
            self.stop_btn.setEnabled(True)
            self.start_btn.clearFocus()
            self.idle_start_btn.clearFocus()
            self.game_btn.clearFocus()
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self._set_session_controls_locked(True)

    def _open_scratch_window(self) -> None:
        from ui.scratch_game_window import ScratchGameWindow

        QApplication.processEvents()
        if self._scratch_window is not None:
            self._detach_scratch_window()

        def _on_tile(en2: int, tid: int) -> bool:
            ok, msg = self.controller.enqueue_game_at(int(en2), int(tid))
            if not ok and self._scratch_window is not None:
                self._scratch_window.lbl_event.setText(
                    f"EN2 {en2} tile {tid}: {msg}"
                )
                self._scratch_window.lbl_event.setVisible(True)
            return bool(ok)

        win = ScratchGameWindow(
            on_tile=_on_tile,
            on_reload_tiles=self.controller.game_tile_snapshot,
            parent=None,
        )
        win.closed.connect(self._on_scratch_window_closed)
        self._scratch_window = win
        self.controller.set_game_board_open(True)
        win.show()
        win.raise_()
        win.activateWindow()

    def _on_scratch_window_closed(self) -> None:
        """User closed Game Mode window → same teardown as Stop."""
        self._scratch_window = None
        try:
            self.controller.set_game_board_open(False)
        except Exception:
            pass
        if self._stop_busy:
            self._set_session_controls_locked(False)
            return
        if self.controller.is_running() or self._idle_session_active():
            self._on_stop()
        else:
            self._set_session_controls_locked(False)

    def _detach_scratch_window(self) -> None:
        """Close the board without treating it as a user Stop request."""
        win = self._scratch_window
        self._scratch_window = None
        if win is None:
            return
        try:
            win.closed.disconnect(self._on_scratch_window_closed)
        except TypeError:
            pass
        try:
            win.close()
        except Exception:
            pass
        try:
            self.controller.set_game_board_open(False)
        except Exception:
            pass

    def _close_scratch_window(self) -> None:
        self._detach_scratch_window()

    def _stop_idle_session_to_stopped(self) -> None:
        from worker.idle_session import IdleSessionState

        self._idle_state = IdleSessionState.STOPPED
        self._idle_launching = False
        self.controller.update_idle_options(enabled=False)
        self._set_session_controls_locked(False)
        self._set_activity_ui_waiting("")
        self._refresh_header_chips()

    def _on_stop(self) -> None:
        from worker.idle_session import IdleSessionState

        def _after(ok: bool) -> None:
            if not ok:
                QMessageBox.warning(
                    self,
                    "Could not stop",
                    "Miner thread or process did not exit in time. "
                    "New session / network change blocked. Try Stop again.",
                )
                self.stop_btn.setEnabled(True)
                self._set_session_controls_locked(True)
                return
            self._close_scratch_window()
            self._stop_idle_session_to_stopped()
            self.lbl_status.setText("Stopped.")
            self._persist_form()

        # WAITING_FOR_IDLE: no miner process — stop monitoring only.
        if (
            self._idle_state == IdleSessionState.WAITING_FOR_IDLE
            and not self.controller.is_running()
            and not self._stop_busy
        ):
            self._stop_idle_session_to_stopped()
            self.lbl_status.setText("Idle Mode cancelled.")
            self._persist_form()
            return

        self._begin_async_stop(_after)

    def _sync_idle_controls_if_needed(self) -> None:
        """Unlock Start on natural session end (battery/process); do not touch on stop_failed."""
        from worker.idle_session import IdleSessionState

        if self._stop_busy:
            return
        if self.controller._stop_failed:
            return
        if self.controller.is_running():
            return
        if self._idle_state == IdleSessionState.WAITING_FOR_IDLE:
            self._set_session_controls_locked(True)
            return
        if self._idle_state in (
            IdleSessionState.MINING_IDLE,
            IdleSessionState.MINING_ACTIVE,
        ):
            # Miner died while Idle session was mining — end session.
            self._stop_idle_session_to_stopped()
            return
        if self.stop_btn.isEnabled() and not self.start_btn.isEnabled():
            self._set_session_controls_locked(False)

    def _apply_stats(self, stats: MiningStats) -> None:
        try:
            self._apply_stats_inner(stats)
        except Exception:
            # Never let a UI stats tick kill the process (PyQt slot abort).
            import traceback

            traceback.print_exc()

    def _apply_stats_inner(self, stats: MiningStats) -> None:
        self._sync_idle_controls_if_needed()
        if self._scratch_window is not None and getattr(
            stats, "session_kind", ""
        ) in ("game", "both"):
            try:
                self._scratch_window.apply_stats(stats)
            except Exception:
                import traceback

                traceback.print_exc()
        conn_txt = (
            "TEST (local)"
            if stats.test_mode and stats.connected
            else ("Connected" if stats.connected else "Not connected")
        )
        self.lbl_conn.setText(conn_txt)
        self._refresh_header_chips(connected=bool(stats.connected), conn_txt=conn_txt)
        mode = getattr(stats, "activity_mode", "off") or "off"
        ui = (getattr(stats, "activity_ui", "") or "").strip()
        if mode == "off":
            self.lbl_activity.setText("Off")
            activity_tip = ""
        elif ui:
            self.lbl_activity.setText(ui)
            activity_tip = (
                "Using PC" if ("Using PC" in ui or "ACTIVE" in ui) else (
                    "AFK" if ("AFK" in ui or "IDLE" in ui) else ui
                )
            )
        elif mode == "active":
            self.lbl_activity.setText("Using PC · reduced / paused")
            activity_tip = "Using PC"
        elif mode == "idle":
            self.lbl_activity.setText("AFK · AFK intensity")
            activity_tip = "AFK"
        else:
            self.lbl_activity.setText(str(mode))
            activity_tip = str(mode)
        if self.tray is not None and self._idle_session_active():
            from worker.idle_session import IdleSessionState

            base = APP_NAME
            st = self._idle_state
            if st == IdleSessionState.WAITING_FOR_IDLE:
                self.tray.setToolTip(f"{base} — Idle Mode · waiting")
            elif self.controller.is_running() and activity_tip:
                self.tray.setToolTip(f"{base} — Idle Mode · {activity_tip}")
            elif self.controller.is_running():
                self.tray.setToolTip(f"{base} — Idle Mode · mining")
            else:
                self.tray.setToolTip(f"{base} — Idle Mode")
        self.lbl_device.setText(stats.device_name or "—")
        rate = stats.hashrate
        if rate >= 1_000_000:
            self.lbl_rate.setText(f"{rate / 1_000_000:.2f} MH/s")
        elif rate >= 1000:
            self.lbl_rate.setText(f"{rate / 1000:.2f} kH/s")
        else:
            self.lbl_rate.setText(f"{rate:.0f} H/s")
        managed = self._profile.engine_kind == "managed_external"
        is_xmr = self._network_id == "xmr"
        if managed and not is_xmr:
            self.lbl_total.setText("— (external engine)")
        else:
            self.lbl_total.setText(f"{stats.total_hashes:,}")
            life = getattr(stats, "lifetime_attempts", None)
            if life is None:
                from mining.lifetime_stats import get_lifetime_attempts

                life = get_lifetime_attempts(self._network_id)
            self.lbl_lifetime.setText(f"{int(life):,}")
        self.lbl_time.setText(f"{stats.elapsed:.0f}s")
        self.lbl_shares.setText(f"accepted {stats.accepted} / rejected {stats.rejected}")
        self._update_scoreboard(
            int(getattr(stats, "block_candidate_count", 0) or 0),
            int(stats.accepted or 0),
            int(stats.rejected or 0),
            int(stats.total_hashes or 0) if (not managed or is_xmr) else 0,
        )
        self._apply_best_stats(stats)
        self.lbl_engine_fee.setText(
            f"Engine fee shares (not user accepted): {getattr(stats, 'engine_fee_shares', 0)}"
        )
        self.lbl_unattributed.setText(
            f"Unattributed shares (not accepted): "
            f"{getattr(stats, 'unattributed_shares', 0)}"
        )
        if getattr(stats, "thermal_source", ""):
            self.lbl_thermal_src.setText(f"Temperature source: {stats.thermal_source}")
        elif self._profile.thermal_source == "cpu":
            self.lbl_thermal_src.setText(
                "Temperature source: CPU (no auto pause if unreadable)"
            )
        if stats.server_difficulty is not None:
            self.lbl_diff.setText(str(stats.server_difficulty))
        elif stats.difficulty:
            self.lbl_diff.setText(f"{stats.difficulty} (waiting for set_difficulty)")
        else:
            self.lbl_diff.setText("—")
        self.lbl_job.setText(stats.current_job_id or "—")
        self.lbl_payout.setText(stats.payout_address or "—")
        coinbase = stats.coinbase_status or "—"
        banner = getattr(stats, "pool_banner", "") or ""
        kind = getattr(stats, "pool_kind", "") or ""
        if banner and banner not in coinbase:
            coinbase = f"{coinbase} | {banner}" if coinbase != "—" else banner
        if kind and kind != "solo":
            coinbase = f"[{kind.upper()}] {coinbase}"
        self.lbl_coinbase.setText(coinbase)
        if stats.block_store_error:
            self.lbl_coinbase.setText(
                coinbase + f" | Store: {stats.block_store_error}"
            )
        if banner:
            self.lbl_pool_banner.setText(banner)
            self.lbl_pool_banner.setVisible(True)
        self._refresh_stats_link_ui(stats.ckpool_stats_url or "")
        if stats.submit_rpc_log:
            lines = []
            for e in stats.submit_rpc_log[:15]:
                lines.append(
                    f"id={e.get('id')} sent={e.get('time_sent')} recv={e.get('time_recv')} "
                    f"ok={e.get('ok')} req={e.get('request')} resp={e.get('response')}"
                )
            self.submit_log_view.setPlainText("\n".join(lines))
        if stats.temp_readable and stats.gpu_temp is not None:
            extra = " · paused" if stats.paused_thermal else ""
            self.lbl_temp.setText(f"{stats.gpu_temp}°C{extra}")
            self._update_scoreboard_temp(int(stats.gpu_temp))
            self._refresh_thermal_unsafe_banner(running_without_temp=False)
        else:
            self._update_scoreboard_temp(None)
            self.lbl_temp.setText("unreadable · all mining paused until fixed")
            self._refresh_thermal_unsafe_banner(running_without_temp=False)
        if managed:
            self.lbl_work.setText(
                f"External engine · rate={self.lbl_rate.text()} · "
                f"share accepted={stats.accepted} rejected={stats.rejected} · "
                f"{(stats.status or '')[:80]}"
            )
        elif stats.last_scanned:
            strat = getattr(stats, "search_strategy", None) or "sequential"
            self.lbl_work.setText(
                f"strategy={strat}   scanned={stats.last_scanned:,}   "
                f"global={stats.last_global:,}  local={stats.last_local}   "
                f"kernel={stats.last_kernel_ms:.1f}ms   sleep={stats.last_sleep_s * 1000:.0f}ms"
            )
        else:
            self.lbl_work.setText("no kernel yet (connected ≠ hashing)")
        self.lbl_status.setText(stats.status)
        self._refresh_search_strategy_ui()
        st = (stats.status or "").lower()
        if (
            not self._defender_help_shown
            and ("windows security" in st or "coinminer" in st)
            and "blocked" in st
        ):
            self._defender_help_shown = True
            from ui.defender_help_dialog import show_defender_help

            label = "XMRig" if self._network_id == "xmr" else "Rigel"
            QTimer.singleShot(0, lambda: show_defender_help(self, label))

        # Block candidate panel
        self.lbl_blk_count.setText(str(stats.block_candidate_count))
        blk = stats.last_block
        if blk:
            self.block_alert.setVisible(True)
            if blk.get("loaded_from_disk"):
                self.lbl_block_alert_title.setText("Stored block candidate")
                self.lbl_block_alert_body.setText(
                    "Historical record loaded from disk. This does not mean a block "
                    "was just found or submitted to the pool."
                )
            else:
                self.lbl_block_alert_title.setText(
                    "BLOCK CANDIDATE FOUND" + (" (TEST)" if blk.get("test_mode") else "")
                )
                self.lbl_block_alert_body.setText(
                    f"Candidate submitted to pool / saved. {self._profile.display_name} "
                    "network shows no earned reward until acceptance. "
                    "Chain verification is not proof of payment."
                )
            self.lbl_blk_time.setText(str(blk.get("time") or "—"))
            self.lbl_blk_nonce.setText(
                str(blk.get("nonce_hex") or blk.get("nonce") or "—")
            )
            self.lbl_blk_job.setText(str(blk.get("job_id") or "—"))
            self.lbl_blk_status.setText(str(blk.get("status") or "—"))
            self.lbl_blk_chain.setText(
                str(blk.get("chain_status") or blk.get("chain_detail") or "—")
            )
            self.lbl_blk_hash.setText(str(blk.get("hash") or "—"))
            if blk.get("test_mode") and not blk.get("loaded_from_disk"):
                self.lbl_block_alert_body.setText(
                    "TEST candidate — no real earnings / chain confirmation."
                )
        else:
            self.block_alert.setVisible(False)
            self.lbl_blk_time.setText("—")
            self.lbl_blk_nonce.setText("—")
            self.lbl_blk_job.setText("—")
            self.lbl_blk_status.setText("None yet")
            self.lbl_blk_chain.setText("—")
            self.lbl_blk_hash.setText("—")

        self.block_list.setPlainText(
            "\n".join(
                f"[{b.get('time')}] nonce={b.get('nonce_hex') or b.get('nonce')}  "
                f"{b.get('hash')}  | {b.get('status')}  | chain={b.get('chain_status')}"
                for b in stats.block_candidates
            )
            or ""
        )

        # Share panel (pool target; block candidates in separate panel)
        self.lbl_sh_count.setText(str(stats.share_submit_count))
        self.lbl_sh_acc.setText(f"{stats.accepted} / {stats.rejected}")
        sh = stats.last_share
        if sh:
            self.lbl_sh_nonce.setText(str(sh.get("nonce_hex") or sh.get("nonce") or "—"))
            self.lbl_sh_status.setText(str(sh.get("status") or "—"))
            self.lbl_sh_hash.setText(str(sh.get("hash") or "—"))
        else:
            self.lbl_sh_nonce.setText("—")
            self.lbl_sh_status.setText("None yet")
            self.lbl_sh_hash.setText("—")

        self.share_list.setPlainText(
            "\n".join(
                f"[{s.get('time')}] nonce={s.get('nonce_hex') or s.get('nonce')}  "
                f"{s.get('hash')}  | {s.get('status')}"
                for s in stats.share_events
            )
        )
        self.event_log.setPlainText("\n".join(stats.event_log))
        self._maybe_notify_thermal(stats)
        self._maybe_notify_block(stats)

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return

        self.tray = QSystemTrayIcon(self)
        icon = _make_tray_icon()
        style_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray.setIcon(icon if not icon.isNull() else style_icon)
        self.setWindowIcon(self.tray.icon())
        self.tray.setToolTip(APP_NAME)

        menu = QMenu()
        act_show = QAction("Show window", self)
        act_show.triggered.connect(self._show_from_tray)
        act_hide = QAction("Minimize to tray", self)
        act_hide.triggered.connect(self.hide)
        act_settings = QAction("Mining Settings…", self)
        act_settings.triggered.connect(lambda: self._open_settings(focus="mining"))
        act_idle = QAction("Idle Mode Settings…", self)
        act_idle.triggered.connect(lambda: self._open_settings(focus="idle"))
        act_exit = QAction("Exit", self)
        act_exit.triggered.connect(self._quit_app)
        act_how = QAction("How to Use…", self)
        act_how.triggered.connect(self._show_howto)
        act_about = QAction(f"About {APP_SHORT}…", self)
        act_about.triggered.connect(self._show_about)
        act_upd = QAction("Check for Updates…", self)
        act_upd.triggered.connect(lambda: self._check_for_updates(manual=True))
        self._act_show_scoreboard = QAction("Show scoreboard", self)
        self._act_show_scoreboard.triggered.connect(self._on_tray_show_scoreboard)
        menu.addAction(act_show)
        menu.addAction(act_hide)
        menu.addAction(act_settings)
        menu.addAction(act_idle)
        menu.addAction(self._act_show_scoreboard)
        menu.addSeparator()
        menu.addAction(act_how)
        menu.addAction(act_about)
        menu.addAction(act_upd)
        menu.addSeparator()
        menu.addAction(act_exit)
        self.tray.setContextMenu(menu)
        self._refresh_scoreboard_tray_action()
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        # No startup balloon — Windows queues these and they keep popping after exit.

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self._show_from_tray()

    def raise_to_front(self) -> None:
        """Show and activate the main window (tray click or second-instance launch)."""
        self._hide_scoreboard_overlay()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _show_from_tray(self) -> None:
        self.raise_to_front()

    def _scoreboard_overlay_enabled(self) -> bool:
        return bool(self._cfg.get("scoreboard_overlay_enabled", True))

    def _set_scoreboard_overlay_enabled(self, enabled: bool) -> None:
        self._cfg["scoreboard_overlay_enabled"] = bool(enabled)
        save_settings({"scoreboard_overlay_enabled": bool(enabled)})
        self._refresh_scoreboard_tray_action()

    def _refresh_scoreboard_tray_action(self) -> None:
        act = getattr(self, "_act_show_scoreboard", None)
        if act is None:
            return
        # Offer re-enable when user dismissed the overlay
        act.setEnabled(not self._scoreboard_overlay_enabled())

    def _update_scoreboard(
        self, blocks: int, accepted: int, rejected: int, attempts: int
    ) -> None:
        self._last_scoreboard = (blocks, accepted, rejected, attempts)
        self.scoreboard.update_counts(blocks, accepted, rejected, attempts)
        if self._scoreboard_overlay is not None:
            self._scoreboard_overlay.update_counts(blocks, accepted, rejected, attempts)
        QTimer.singleShot(0, self._fit_chrome_to_scoreboard)

    def _difficulty_row_visible(self) -> bool:
        return self._network_id in SUPPORTED_BEST_HASH_NETWORKS

    def _push_difficulty_row(self) -> None:
        vis = self._difficulty_row_visible()
        net, best, acc, last = (
            self._last_net_diff,
            self._last_best_diff,
            self._last_accepted_best_diff,
            self._last_accepted_diff,
        )
        self.scoreboard.set_difficulty_row(
            net, best, visible=vis, accepted_best=acc, last_accepted=last
        )
        if self._scoreboard_overlay is not None:
            self._scoreboard_overlay.set_difficulty_row(
                net, best, visible=vis, accepted_best=acc, last_accepted=last
            )

    def _load_stored_best_into_row(self) -> None:
        """Idle startup / network switch: show stored best for current network."""
        self._last_net_diff = None
        self._last_best_diff = None
        self._last_accepted_best_diff = None
        self._last_accepted_diff = None
        gpu_diff = None
        acc_diff = None
        if self._difficulty_row_visible():
            try:
                net_rec = load_best_hash_state()["records"].get(self._network_id)
            except Exception:
                net_rec = None
            if net_rec is not None:
                if net_rec.gpu_best is not None:
                    gpu_diff = net_rec.gpu_best.difficulty
                if net_rec.accepted_best is not None:
                    acc_diff = net_rec.accepted_best.difficulty
            net, best = idle_difficulty_row(gpu_diff)
            self._last_net_diff, self._last_best_diff = net, best
            self._last_accepted_best_diff = acc_diff
        self._push_difficulty_row()
        self._set_status_best_labels(gpu_diff, acc_diff, visible=self._difficulty_row_visible())

    def _set_status_best_labels(
        self,
        gpu_diff: float | None,
        acc_diff: float | None,
        *,
        visible: bool,
    ) -> None:
        for w in (
            self.lbl_gpu_best_k,
            self.lbl_gpu_best,
            self.lbl_acc_best_k,
            self.lbl_acc_best,
        ):
            w.setVisible(visible)
        if not visible:
            return
        self.lbl_gpu_best.setText(format_diff_short(gpu_diff))
        self.lbl_acc_best.setText(format_diff_short(acc_diff))

    def _hide_accepted_best_banner(self) -> None:
        self.lbl_accepted_best_banner.setVisible(False)
        self.lbl_accepted_best_banner.setText("")
        self.lbl_acc_best.setStyleSheet("")

    def _celebrate_accepted_best(self) -> None:
        self.lbl_accepted_best_banner.setText("NEW ACCEPTED BEST")
        self.lbl_accepted_best_banner.setVisible(True)
        self.lbl_acc_best.setStyleSheet("color: #2e7d32; font-weight: 700;")
        self._accepted_best_banner_timer.start(1600)

    def _apply_best_stats(self, stats: MiningStats) -> None:
        if self._difficulty_row_visible():
            net = getattr(stats, "network_difficulty", None)
            best = getattr(stats, "best_difficulty", None)
            if net is not None:
                self._last_net_diff = net
            if best is not None:
                self._last_best_diff = best
            gpu_live = getattr(stats, "best_difficulty", None)
            acc_live = getattr(stats, "accepted_best_difficulty", None)
            if acc_live is not None:
                self._last_accepted_best_diff = acc_live
            last_live = getattr(stats, "last_accepted_difficulty", None)
            if last_live is not None:
                self._last_accepted_diff = last_live
            self._set_status_best_labels(
                gpu_live if gpu_live is not None else self._last_best_diff,
                acc_live if acc_live is not None else self._last_accepted_best_diff,
                visible=True,
            )
        else:
            self._last_accepted_diff = None
            self._set_status_best_labels(None, None, visible=False)
        self._push_difficulty_row()
        if getattr(stats, "best_record_broken", False) and self._difficulty_row_visible():
            self.scoreboard.celebrate_record()
            if self._scoreboard_overlay is not None:
                self._scoreboard_overlay.celebrate_record()
        if getattr(stats, "accepted_record_broken", False) and self._difficulty_row_visible():
            self._celebrate_accepted_best()

    def _update_scoreboard_temp(self, temp_c: int | None) -> None:
        self._last_scoreboard_temp = temp_c
        self.scoreboard.update_temp(temp_c)
        if self._scoreboard_overlay is not None:
            self._scoreboard_overlay.update_temp(temp_c)

    def _maybe_show_scoreboard_overlay(self) -> None:
        if self._tray_exit:
            return
        if not self._scoreboard_overlay_enabled():
            return
        if self._scoreboard_overlay is None:
            return
        b, a, r, t = self._last_scoreboard
        self._scoreboard_overlay.update_counts(b, a, r, t)
        self._scoreboard_overlay.update_temp(self._last_scoreboard_temp)
        self._scoreboard_overlay.set_difficulty_row(
            self._last_net_diff,
            self._last_best_diff,
            visible=self._difficulty_row_visible(),
            accepted_best=self._last_accepted_best_diff,
            last_accepted=self._last_accepted_diff,
        )
        self._scoreboard_overlay.show_overlay()
        self._refresh_scoreboard_tray_action()

    def _hide_scoreboard_overlay(self) -> None:
        if self._scoreboard_overlay is not None and self._scoreboard_overlay.isVisible():
            self._scoreboard_overlay.hide()

    def _teardown_scoreboard_for_quit(self) -> None:
        """Stop LED timers + destroy tray overlay before QApplication.quit()."""
        try:
            self.scoreboard.stop_alerts()
        except Exception:
            pass
        ov = self._scoreboard_overlay
        if ov is None:
            return
        try:
            ov._on_user_close = None
            ov.stop_alerts()
            ov.hide()
            ov.close()
            ov.deleteLater()
        except Exception:
            pass
        self._scoreboard_overlay = None

    def _wait_background_workers(self, timeout_ms: int = 4000) -> None:
        """Avoid native abort from destroying QThread owners while still running."""
        for w in (
            self._idle_prep_worker,
            self._update_check_worker,
            self._update_prepare_worker,
            self._capacity_worker,
            self._miner_dl_worker,
            self._stop_worker,
        ):
            if w is None:
                continue
            try:
                if w.isRunning():
                    w.wait(timeout_ms)
            except Exception:
                pass

    def _teardown_for_quit(self) -> None:
        """Full safe shutdown hook (aboutToQuit / Quit menu / update apply)."""
        self._teardown_scoreboard_for_quit()
        self._wait_background_workers()

    def _on_scoreboard_overlay_closed(self) -> None:
        self._set_scoreboard_overlay_enabled(False)
        if self.tray is not None and self.tray.isVisible():
            self.tray.setToolTip(
                f"{APP_NAME} — still running (scoreboard hidden)"
            )
            if not self._scoreboard_hide_tip_shown:
                self._scoreboard_hide_tip_shown = True
                self.tray.showMessage(
                    APP_NAME,
                    "Scoreboard hidden. Tray menu → Show scoreboard to bring it back.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2500,
                )

    def _on_tray_show_scoreboard(self) -> None:
        self._set_scoreboard_overlay_enabled(True)
        if not self.isVisible() or self.isMinimized():
            self._maybe_show_scoreboard_overlay()
        else:
            # Main window visible — overlay only while trayed; just re-enable for next hide
            self._hide_scoreboard_overlay()

    def _open_settings(
        self, *, focus_idle: bool = False, focus: str | None = None
    ) -> None:
        def _after_reset_records() -> None:
            self.controller.reload_best_hash_records()
            self._load_stored_best_into_row()
            self._hide_accepted_best_banner()

        dlg = SettingsDialog(
            self._cfg,
            self,
            on_reset_records=_after_reset_records,
            network_id=self._network_id,
        )
        dlg.form.pick_gpu_clicked.connect(self._on_pick_gpu)
        if self._network_id == "xmr":
            dlg.form.set_binary_idle_ui(True, engine="xmr")
        elif self._profile.engine_kind == "managed_external":
            dlg.form.set_binary_idle_ui(True, engine="rigel")
        else:
            dlg.form.set_binary_idle_ui(False, engine="native")
        section = focus or ("idle" if focus_idle else None)
        if section == "idle" and hasattr(dlg.form, "lbl_idle_note"):
            dlg.form.lbl_idle_note.setStyleSheet(
                "color: #9a3412; font-weight: 700;"
            )
            QTimer.singleShot(0, lambda: dlg.form.idle_timeout.setFocus())
        elif section == "hardware" and hasattr(dlg.form, "lbl_thermal_hint"):
            dlg.setWindowTitle("Hardware & Temperature — Easy Block Finder 4000")
            QTimer.singleShot(0, lambda: dlg.form.pause_temp.setFocus())
        elif section == "mining":
            dlg.setWindowTitle("Mining Settings — Easy Block Finder 4000")
            QTimer.singleShot(0, lambda: dlg.form.intensity.setFocus())
        if dlg.exec():
            vals = dlg.values()
            overlay = bool(vals.pop("scoreboard_overlay_enabled", True))
            vals["idle_settings_configured"] = True
            self._cfg.update(vals)
            save_settings(vals)
            self._cfg = load_settings()
            self._push_settings()
            self._set_scoreboard_overlay_enabled(overlay)
            if not self.isVisible() or self.isMinimized():
                if overlay:
                    self._maybe_show_scoreboard_overlay()
                else:
                    self._hide_scoreboard_overlay()
            else:
                self._hide_scoreboard_overlay()
            if self.controller.is_running():
                self.controller.update_cpu_options(
                    cpu_thread_limit=self._cpu_threads_val(),
                    pause_on_battery=self._pause_battery_val(),
                    xmrig_donate_level=int(self._cfg.get("xmrig_donate_level") or 1),
                )

    def _quit_from_menu(self) -> None:
        """File → Exit: confirm, then full exit (same path as tray Exit)."""
        reply = QMessageBox.question(
            self,
            "Exit",
            "Exit Easy Block Finder 4000?\n\n"
            "Mining will stop and the app will exit completely "
            "(it will not stay in the tray).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._quit_app()

    def _ensure_quit_busy_overlay(self) -> None:
        if self._quit_busy_host is not None:
            return
        host = QWidget(self)
        host.setObjectName("quitBusyHost")
        host.setStyleSheet(
            "QWidget#quitBusyHost { background: rgba(238, 241, 244, 220); }"
        )
        lay = QVBoxLayout(host)
        lay.setContentsMargins(48, 48, 48, 48)
        lay.addStretch(1)
        self._quit_busy = BusyIndicator(host)
        lay.addWidget(self._quit_busy, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        host.hide()
        self._quit_busy_host = host

    def _ensure_game_busy_overlay(self) -> None:
        if self._game_busy_host is not None:
            return
        host = QWidget(self)
        host.setObjectName("gameBusyHost")
        host.setStyleSheet(
            "QWidget#gameBusyHost { background: rgba(238, 241, 244, 220); }"
        )
        lay = QVBoxLayout(host)
        lay.setContentsMargins(48, 48, 48, 48)
        lay.addStretch(1)
        self._game_busy = BusyIndicator(host)
        lay.addWidget(self._game_busy, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        host.hide()
        self._game_busy_host = host

    def _show_game_busy(self, message: str = "Opening Game Mode…") -> None:
        """Loading circle until the scratch board window is ready."""
        self._ensure_game_busy_overlay()
        assert self._game_busy_host is not None and self._game_busy is not None
        self._game_busy_host.setGeometry(self.rect())
        self._game_busy_host.raise_()
        self._game_busy_host.show()
        self._game_busy.show_busy(message or "Opening Game Mode…")
        self.game_btn.setEnabled(False)
        QApplication.processEvents()

    def _hide_game_busy(self) -> None:
        if self._game_busy is not None:
            self._game_busy.hide_busy()
        if self._game_busy_host is not None:
            self._game_busy_host.hide()
        # Re-apply enable rules (busy path forces game_btn off).
        try:
            locked = bool(self.controller.is_running()) or bool(
                self._idle_session_active()
            )
            self._set_session_controls_locked(locked)
        except Exception:
            self.game_btn.setEnabled(True)

    def _show_quit_busy(self, message: str = "Quitting…") -> None:
        """Full-window spinner while stop/teardown runs (Quit can take a moment)."""
        self._ensure_quit_busy_overlay()
        assert self._quit_busy_host is not None and self._quit_busy is not None
        # Cover the whole window (menu bar included)
        self._quit_busy_host.setGeometry(self.rect())
        self._quit_busy_host.raise_()
        self._quit_busy_host.show()
        self._quit_busy.show_busy(
            message or "Quitting… Stopping miners and cleaning up."
        )
        self.setEnabled(False)
        QApplication.processEvents()

    def _fit_chrome_to_scoreboard(self) -> None:
        """Align chrome width to scoreboard, but never crush the control row."""
        if not hasattr(self, "_chrome_band") or not hasattr(self, "scoreboard"):
            return
        # Clear any prior fixed width so sizeHint reflects digit content.
        self.scoreboard.setMinimumWidth(0)
        self.scoreboard.setMaximumWidth(16777215)
        self.scoreboard.adjustSize()
        board_w = max(
            1,
            self.scoreboard.sizeHint().width(),
            self.scoreboard.minimumSizeHint().width(),
        )
        ctrl_w = 0
        if hasattr(self, "_ctrl_row") and self._ctrl_row is not None:
            self._ctrl_row.adjustSize()
            ctrl_w = max(
                self._ctrl_row.sizeHint().width(),
                self._ctrl_row.minimumSizeHint().width(),
            )
        w = max(board_w, ctrl_w)
        self._chrome_band.setFixedWidth(w)
        self.scoreboard.setFixedWidth(w)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # Screen is reliable after show — re-cap to available desktop height.
        self._clamp_window_to_screen()
        QTimer.singleShot(0, self._fit_chrome_to_scoreboard)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._quit_busy_host is not None and self._quit_busy_host.isVisible():
            self._quit_busy_host.setGeometry(self.rect())
        if self._game_busy_host is not None and self._game_busy_host.isVisible():
            self._game_busy_host.setGeometry(self.rect())

    def _on_setup_wizard_finished(self, updates: dict) -> None:
        updates = dict(updates)
        updates["scoreboard_overlay_enabled"] = True
        self._cfg.update(updates)
        save_settings(updates)
        self._cfg = load_settings()
        self._push_settings()
        self._set_scoreboard_overlay_enabled(True)
        self._stack.setCurrentWidget(self._select_page)

    def _rerun_setup_wizard(self) -> None:
        idx = self._stack.indexOf(self._setup_wizard)
        if idx >= 0:
            self._stack.removeWidget(self._setup_wizard)
            self._setup_wizard.deleteLater()
        self._setup_wizard = SetupWizardPage(self._cfg)
        self._setup_wizard.finished.connect(self._on_setup_wizard_finished)
        self._stack.insertWidget(0, self._setup_wizard)
        self._stack.setCurrentWidget(self._setup_wizard)

    def _notify(self, title: str, body: str, icon=None) -> None:
        if icon is None:
            icon = QSystemTrayIcon.MessageIcon.Warning
        if self.tray is not None and self.tray.isVisible():
            self.tray.showMessage(title, body, icon, 8000)
            self.tray.setToolTip(f"{APP_NAME} — {body[:80]}")

    def _maybe_notify_thermal(self, stats: MiningStats) -> None:
        paused = bool(stats.paused_thermal)
        if self._last_thermal_paused is None:
            self._last_thermal_paused = paused
            return
        if paused == self._last_thermal_paused:
            return
        self._last_thermal_paused = paused
        temp = stats.gpu_temp
        if paused:
            self._notify(
                f"{APP_NAME} — thermal pause",
                f"GPU {temp}°C: mining paused "
                f"(threshold {self._pause_temp_val()}°C). Resumes automatically when cooler.",
                QSystemTrayIcon.MessageIcon.Warning,
            )
        else:
            self._notify(
                f"{APP_NAME} — resumed",
                f"GPU {temp}°C: cooled down, mining restarted "
                f"(resume ≤ {self._resume_temp_val()}°C).",
                QSystemTrayIcon.MessageIcon.Information,
            )

    def _maybe_notify_block(self, stats: MiningStats) -> None:
        blk = stats.last_block
        if not blk:
            return
        key = (
            f"{blk.get('job_id')}|{blk.get('nonce_hex') or blk.get('nonce')}|"
            f"{blk.get('hash')}|{blk.get('time')}"
        )
        if key == self._last_block_notify_key:
            return
        # Disk history — lock key, no tray "just found" notification
        if blk.get("loaded_from_disk"):
            self._last_block_notify_key = key
            return
        self._last_block_notify_key = key
        nonce = blk.get("nonce_hex") or blk.get("nonce") or "?"
        digest = str(blk.get("hash") or "")
        digest_short = f"{digest[:20]}…" if len(digest) > 20 else (digest or "—")
        test = " (TEST — not a payout)" if blk.get("test_mode") else ""
        self._notify(
            f"{APP_NAME} — BLOCK CANDIDATE{test}",
            f"nonce={nonce}  hash={digest_short}  "
            "Not a payout until accepted on the network.",
            QSystemTrayIcon.MessageIcon.Critical,
        )

    def _force_stop_all_miners(self) -> None:
        """Best-effort: controller stop leftovers + kill AppData XMRig/Rigel."""
        try:
            from engines.orphan_miners import kill_app_miners

            kill_app_miners()
        except Exception:
            pass

    def _quit_app(self) -> None:
        self._persist_form()
        if self._stop_busy:
            return

        self._show_quit_busy("Quitting… Stopping miners and cleaning up.")

        def _after(ok: bool) -> None:
            self._show_quit_busy("Quitting… Finishing cleanup.")
            self._force_stop_all_miners()
            if not ok:
                # Still force-kill orphans; if something remains, warn but exit UI
                try:
                    from engines.orphan_miners import list_app_miners

                    left = list_app_miners()
                except Exception:
                    left = []
                if left:
                    self.setEnabled(True)
                    if self._quit_busy_host is not None:
                        self._quit_busy_host.hide()
                    QMessageBox.warning(
                        self,
                        "Could not stop cleanly",
                        "Some miner processes may still be running. "
                        "They were signalled to terminate; check Task Manager if needed.",
                    )
            self._tray_exit = True
            self._teardown_for_quit()
            if self.tray is not None:
                self.tray.hide()
            QApplication.instance().quit()

        self._pending_quit = True
        try:
            from engines.orphan_miners import list_app_miners

            orphans = list_app_miners()
        except Exception:
            orphans = []
        if (
            not self.controller.is_running()
            and not self.controller._stop_failed
            and not orphans
        ):
            _after(True)
            return
        self._begin_async_stop(_after)

    def changeEvent(self, event) -> None:  # noqa: N802
        # stay in tray when minimized from taskbar
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            if self.tray is not None and self.tray.isVisible():
                QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        if self._tray_exit:
            self._hide_scoreboard_overlay()
            return
        # Minimized / closed to tray → optional LED overlay
        QTimer.singleShot(0, self._maybe_show_scoreboard_overlay)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._persist_form()
        if self._tray_exit or self.tray is None:
            self._teardown_for_quit()
            if self._stop_busy:
                event.ignore()
                return
            try:
                from engines.orphan_miners import list_app_miners

                orphans = list_app_miners()
            except Exception:
                orphans = []
            if (
                self.controller.is_running()
                or self.controller._stop_failed
                or orphans
            ):
                event.ignore()

                def _after(ok: bool) -> None:
                    self._force_stop_all_miners()
                    self._tray_exit = True
                    self._teardown_for_quit()
                    if self.tray is not None:
                        self.tray.hide()
                    self.close()

                self._begin_async_stop(_after)
                return
            self._force_stop_all_miners()
            if self.tray is not None:
                self.tray.hide()
            event.accept()
            return
        # X = minimize to tray, not quit
        event.ignore()
        self.hide()
        # One tip per session only (repeated balloons spam Windows Action Center)
        if self.tray is not None and not self._tray_minimize_tip_shown:
            self._tray_minimize_tip_shown = True
            self.tray.showMessage(
                APP_NAME,
                "Still running in the tray. Double-click to open; tray menu → Exit to exit.",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
