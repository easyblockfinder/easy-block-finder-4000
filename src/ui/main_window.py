"""Single-window Easy Block Finder 4000 UI + system tray."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from app_meta import (
    APP_NAME,
    APP_TITLE,
    APP_VERSION_LABEL,
    load_app_icon,
    load_app_logo_pixmap,
)
from PyQt6.QtCore import QEvent, QObject, QThread, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
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
QTabWidget#mineTabs::pane {
    background: #f7f9fb;
    border: 1px solid #d5dde5;
    border-radius: 10px;
    top: -1px;
    padding: 4px;
}
QTabWidget#mineTabs QTabBar::tab {
    background: #e8edf2;
    color: #4a5a68;
    border: 1px solid #d5dde5;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 14px;
    margin-right: 3px;
    font-weight: 600;
    font-size: 12px;
}
QTabWidget#mineTabs QTabBar::tab:selected {
    background: #f7f9fb;
    color: #0b3d2e;
}
QTabWidget#mineTabs QTabBar::tab:hover:!selected {
    background: #f0f3f6;
    color: #15202b;
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
    padding: 10px 18px;
    font-weight: 700;
    font-size: 13px;
    min-width: 110px;
}
QPushButton#startBtn:hover { background: #0f766e; }
QPushButton#startBtn:disabled { background: #9bb0b8; }
QPushButton#stopBtn {
    background: #ffffff;
    color: #9f1239;
    border: 1px solid #e11d48;
    border-radius: 8px;
    padding: 10px 18px;
    font-weight: 700;
    font-size: 13px;
    min-width: 110px;
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
    padding: 10px 18px;
    font-weight: 700;
    font-size: 13px;
    min-width: 140px;
}
QPushButton#changeNetworkBtn:hover { background: #ecfdf5; }
QPushButton#changeNetworkBtn:disabled {
    color: #9bb0b8;
    border-color: #c8d2dc;
    background: #f0f3f6;
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
    border-radius: 8px;
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
        self.resize(max(680, w), max(640, h))
        self.setMinimumSize(820, 620)

        self._bridge = _StatsBridge()
        self._bridge.updated.connect(self._apply_stats)
        self.controller = MiningController(on_stats=self._bridge.updated.emit)
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
        self._scoreboard_overlay: ScoreboardOverlayWindow | None = None
        self._quit_busy_host: QWidget | None = None
        self._quit_busy: BusyIndicator | None = None

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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._mine_scroll = scroll
        self._stack.addWidget(scroll)

        root = QWidget()
        root.setObjectName("root")
        scroll.setWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        # Logo + scoreboard under it | Donate aligned to logo top-right
        head = QHBoxLayout()
        head.setSpacing(12)
        brand_col = QVBoxLayout()
        brand_col.setSpacing(8)
        logo_pix = load_app_logo_pixmap(440, 96)
        brand = QLabel()
        brand.setObjectName("brand")
        if not logo_pix.isNull():
            brand.setPixmap(logo_pix)
            brand.setMinimumHeight(72)
        else:
            brand.setText(APP_NAME)
            brand.setFont(QFont("Bahnschrift", 26, QFont.Weight.Bold))
        brand_col.addWidget(brand)
        ver = QLabel(APP_VERSION_LABEL)
        ver.setObjectName("tagline")
        brand_col.addWidget(ver)
        self.scoreboard = ScoreboardWidget(compact=False)
        brand_col.addWidget(self.scoreboard)
        head.addLayout(brand_col, 1)

        right_btns = QVBoxLayout()
        right_btns.setSpacing(8)
        right_btns.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self.btn_donate = QPushButton("Donate")
        self.btn_donate.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_donate.setMinimumHeight(36)
        self.btn_donate.setStyleSheet(
            "QPushButton { background: #d32f2f; color: #ffffff; font-weight: 700; "
            "padding: 6px 16px; border-radius: 6px; }"
            "QPushButton:hover { background: #e53935; }"
        )
        self.btn_donate.clicked.connect(self._on_donate)
        right_btns.addWidget(self.btn_donate, 0, Qt.AlignmentFlag.AlignRight)
        right_btns.addStretch(1)
        head.addLayout(right_btns, 0)
        layout.addLayout(head)

        self._scoreboard_overlay = ScoreboardOverlayWindow(
            on_user_close=self._on_scoreboard_overlay_closed,
            parent=None,
        )
        self._scoreboard_overlay.activated.connect(self._show_from_tray)

        net_row = QHBoxLayout()
        self.lbl_network_badge = QLabel("")
        self.lbl_network_badge.setObjectName("sectionTitle")
        net_row.addWidget(self.lbl_network_badge, 1)
        layout.addLayout(net_row)

        self.lbl_tagline = QLabel("")
        self.lbl_tagline.setObjectName("tagline")
        self.lbl_tagline.setWordWrap(True)
        layout.addWidget(self.lbl_tagline)

        diff_note = QLabel(
            "Share difficulty (mining.set_difficulty) is for pool feedback only; "
            "a low share difficulty does not change real block find odds. "
            "The accepted counter increases only when the server mining.submit response has result=true."
        )
        diff_note.setObjectName("tagline")
        diff_note.setWordWrap(True)
        layout.addWidget(diff_note)

        # Start / Stop always visible (not buried in a tab)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setEnabled(False)
        self.btn_change_network = QPushButton("Change network")
        self.btn_change_network.setObjectName("changeNetworkBtn")
        self.btn_change_network.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_change_network.setMinimumHeight(40)
        self.btn_change_network.clicked.connect(self._on_change_network)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        btns.addWidget(self.btn_change_network)
        btns.addStretch(1)
        layout.addLayout(btns)

        tabs = QTabWidget()
        tabs.setObjectName("mineTabs")
        tabs.setDocumentMode(True)
        self._mine_tabs = tabs

        # --- Settings (default) ---
        settings = QWidget()
        s_layout = QVBoxLayout(settings)
        s_layout.setContentsMargins(14, 12, 14, 12)
        s_layout.setSpacing(10)

        self.addr_lbl = QLabel("Payout address")
        self.addr_lbl.setObjectName("statKey")
        s_layout.addWidget(self.addr_lbl)

        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("network wallet address — saved automatically")
        self.address_edit.setMinimumHeight(36)
        self.address_edit.setFont(QFont("Cascadia Mono", 11))
        self.address_edit.editingFinished.connect(self._persist_form)
        self.address_edit.textChanged.connect(self._on_address_changed)
        s_layout.addWidget(self.address_edit)

        self._addr_hint = QLabel("")
        self._addr_hint.setObjectName("statKey")
        self._addr_hint.setWordWrap(True)
        s_layout.addWidget(self._addr_hint)
        self._refresh_addr_hint()

        self.test_mode = QCheckBox("Test mode (no pool, no real submit)")
        self.test_mode.setChecked(bool(self._cfg.get("test_mode")))
        self.test_mode.toggled.connect(self._persist_form)
        s_layout.addWidget(self.test_mode)

        settings_hint = QLabel(
            "Intensity, temperature limits, CPU threads, and GPU pick are in "
            "Settings (menu → Settings…)."
        )
        settings_hint.setObjectName("tagline")
        settings_hint.setWordWrap(True)
        s_layout.addWidget(settings_hint)

        self.lbl_thermal_src = QLabel("Temperature source: —")
        self.lbl_thermal_src.setObjectName("statKey")
        self.lbl_thermal_src.setWordWrap(True)
        s_layout.addWidget(self.lbl_thermal_src)

        self.lbl_thermal_unsafe = QLabel("")
        self.lbl_thermal_unsafe.setWordWrap(True)
        self.lbl_thermal_unsafe.setStyleSheet(
            "color: #d32f2f; font-weight: 700; padding: 4px 0;"
        )
        self.lbl_thermal_unsafe.setVisible(False)
        s_layout.addWidget(self.lbl_thermal_unsafe)
        self._refresh_thermal_unsafe_banner()

        self.lbl_engine_fee = QLabel("Engine fee share: 0")
        self.lbl_engine_fee.setObjectName("statKey")
        s_layout.addWidget(self.lbl_engine_fee)
        self.lbl_unattributed = QLabel("Unattributed shares: 0")
        self.lbl_unattributed.setObjectName("statKey")
        s_layout.addWidget(self.lbl_unattributed)

        fee_hint = QLabel(
            "Note: XMRig/Rigel developer fees are not added to your accepted count. "
            "This app does not redirect mining to donations — use Donate to support."
        )
        fee_hint.setObjectName("tagline")
        fee_hint.setWordWrap(True)
        s_layout.addWidget(fee_hint)
        s_layout.addStretch(1)
        tabs.addTab(settings, "Settings")

        # --- Status ---
        status = QWidget()
        st_outer = QVBoxLayout(status)
        st_outer.setContentsMargins(14, 12, 14, 12)
        st_outer.setSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self.lbl_conn_k, self.lbl_conn = _stat_pair("Connection")
        self.lbl_device_k, self.lbl_device = _stat_pair("Device")
        self.lbl_rate_k, self.lbl_rate = _stat_pair("Hash rate")
        self.lbl_total_k, self.lbl_total = _stat_pair("Total attempts", mono=True)
        self.lbl_time_k, self.lbl_time = _stat_pair("Elapsed")
        self.lbl_shares_k, self.lbl_shares = _stat_pair("Share")
        self.lbl_diff_k, self.lbl_diff = _stat_pair("Server set_difficulty")
        self.lbl_gpu_best_k, self.lbl_gpu_best = _stat_pair("GPU best difficulty")
        self.lbl_acc_best_k, self.lbl_acc_best = _stat_pair("Accepted best difficulty")
        self.lbl_temp_k, self.lbl_temp = _stat_pair("Temperature")
        self.lbl_job_k, self.lbl_job = _stat_pair("Current job ID", mono=True)
        self.lbl_payout_k, self.lbl_payout = _stat_pair("Payout address", mono=True)
        self.lbl_coinbase_k, self.lbl_coinbase = _stat_pair("Coinbase / note")

        pairs = [
            (self.lbl_conn_k, self.lbl_conn),
            (self.lbl_device_k, self.lbl_device),
            (self.lbl_rate_k, self.lbl_rate),
            (self.lbl_total_k, self.lbl_total),
            (self.lbl_time_k, self.lbl_time),
            (self.lbl_shares_k, self.lbl_shares),
            (self.lbl_diff_k, self.lbl_diff),
            (self.lbl_gpu_best_k, self.lbl_gpu_best),
            (self.lbl_acc_best_k, self.lbl_acc_best),
            (self.lbl_temp_k, self.lbl_temp),
            (self.lbl_job_k, self.lbl_job),
            (self.lbl_payout_k, self.lbl_payout),
            (self.lbl_coinbase_k, self.lbl_coinbase),
        ]
        for i, (k, v) in enumerate(pairs):
            r, c = divmod(i, 2)
            grid.addWidget(k, r * 2, c * 2)
            grid.addWidget(v, r * 2 + 1, c * 2, 1, 2)

        st_outer.addLayout(grid)

        self.lbl_accepted_best_banner = QLabel("")
        self.lbl_accepted_best_banner.setObjectName("acceptedBestBanner")
        self.lbl_accepted_best_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_accepted_best_banner.setVisible(False)
        self.lbl_accepted_best_banner.setStyleSheet(
            "color: #1b5e20; font-weight: 700; padding: 4px;"
        )
        st_outer.addWidget(self.lbl_accepted_best_banner)
        self._accepted_best_banner_timer = QTimer(self)
        self._accepted_best_banner_timer.setSingleShot(True)
        self._accepted_best_banner_timer.timeout.connect(self._hide_accepted_best_banner)

        wk = QLabel("Last kernel")
        wk.setObjectName("statKey")
        st_outer.addWidget(wk)
        self.lbl_work = QLabel("no kernel yet (connected ≠ hashing)")
        self.lbl_work.setObjectName("statValMono")
        self.lbl_work.setWordWrap(True)
        self.lbl_work.setMinimumHeight(36)
        self.lbl_work.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        st_outer.addWidget(self.lbl_work)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setObjectName("statusLine")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setMinimumHeight(40)
        st_outer.addWidget(self.lbl_status)

        stats_row = QHBoxLayout()
        self.lbl_stats_url = QLabel("Pool stats: —")
        self.lbl_stats_url.setObjectName("statKey")
        self.lbl_stats_url.setWordWrap(True)
        self.btn_stats = QPushButton("Open pool page")
        self.btn_stats.setEnabled(False)
        self.btn_stats.clicked.connect(self._open_ckpool_stats)
        stats_row.addWidget(self.lbl_stats_url, 1)
        stats_row.addWidget(self.btn_stats, 0)
        st_outer.addLayout(stats_row)
        self.lbl_stats_hint = QLabel(
            "Server stats may lag; with low hash rate / high mindiff they "
            "may not show up immediately."
        )
        self.lbl_stats_hint.setObjectName("statKey")
        self.lbl_stats_hint.setWordWrap(True)
        st_outer.addWidget(self.lbl_stats_hint)

        submit_title = QLabel("mining.submit log (request id)")
        submit_title.setObjectName("statKey")
        st_outer.addWidget(submit_title)
        self.submit_log_view = QTextEdit()
        self.submit_log_view.setReadOnly(True)
        self.submit_log_view.setMinimumHeight(90)
        self.submit_log_view.setFont(QFont("Cascadia Mono", 9))
        self.submit_log_view.setPlaceholderText(
            "Submit request/response pairs match by id here. Accepted only when result=true."
        )
        st_outer.addWidget(self.submit_log_view, 1)
        tabs.addTab(status, "Status")

        # --- Block ---
        block_tab = QWidget()
        bp = QVBoxLayout(block_tab)
        bp.setContentsMargins(14, 12, 14, 12)
        bp.setSpacing(8)

        self.block_alert = QFrame()
        self.block_alert.setObjectName("blockAlert")
        self.block_alert.setVisible(False)
        ba = QVBoxLayout(self.block_alert)
        ba.setContentsMargins(10, 8, 10, 8)
        ba.setSpacing(6)
        self.lbl_block_alert_title = QLabel("BLOCK CANDIDATE")
        self.lbl_block_alert_title.setObjectName("blockAlertTitle")
        ba.addWidget(self.lbl_block_alert_title)
        self.lbl_block_alert_body = QLabel("")
        self.lbl_block_alert_body.setObjectName("blockAlertBody")
        self.lbl_block_alert_body.setWordWrap(True)
        ba.addWidget(self.lbl_block_alert_body)
        bp.addWidget(self.block_alert)

        note = QLabel(
            "No payout is shown until the network accepts the block. This area lists candidates only."
        )
        note.setObjectName("statKey")
        note.setWordWrap(True)
        bp.addWidget(note)

        detail = QFrame()
        detail.setObjectName("blockDetail")
        dg = QGridLayout(detail)
        dg.setContentsMargins(10, 8, 10, 8)
        dg.setHorizontalSpacing(12)
        dg.setVerticalSpacing(6)

        self.lbl_blk_count_k, self.lbl_blk_count = _stat_pair("Candidate count")
        self.lbl_blk_time_k, self.lbl_blk_time = _stat_pair("Time")
        self.lbl_blk_nonce_k, self.lbl_blk_nonce = _stat_pair("Nonce", mono=True)
        self.lbl_blk_job_k, self.lbl_blk_job = _stat_pair("Job ID", mono=True)
        self.lbl_blk_status_k, self.lbl_blk_status = _stat_pair("Submit / pool")
        self.lbl_blk_chain_k, self.lbl_blk_chain = _stat_pair("Chain status")
        self.lbl_blk_hash_k, self.lbl_blk_hash = _stat_pair("Hash", mono=True)

        blk_pairs = [
            (self.lbl_blk_count_k, self.lbl_blk_count),
            (self.lbl_blk_time_k, self.lbl_blk_time),
            (self.lbl_blk_nonce_k, self.lbl_blk_nonce),
            (self.lbl_blk_job_k, self.lbl_blk_job),
            (self.lbl_blk_status_k, self.lbl_blk_status),
            (self.lbl_blk_chain_k, self.lbl_blk_chain),
        ]
        for i, (k, v) in enumerate(blk_pairs):
            r, c = divmod(i, 2)
            dg.addWidget(k, r * 2, c * 2)
            dg.addWidget(v, r * 2 + 1, c * 2, 1, 2)
        dg.addWidget(self.lbl_blk_hash_k, 6, 0)
        dg.addWidget(self.lbl_blk_hash, 7, 0, 1, 4)
        self.lbl_blk_hash.setMinimumHeight(40)
        bp.addWidget(detail)

        self.block_list = QTextEdit()
        self.block_list.setReadOnly(True)
        self.block_list.setMinimumHeight(100)
        self.block_list.setPlaceholderText("No block candidates yet (expected).")
        self.block_list.setFont(QFont("Cascadia Mono", 10))
        bp.addWidget(self.block_list, 1)
        tabs.addTab(block_tab, "Block")

        # --- Shares ---
        share_tab = QWidget()
        sp = QVBoxLayout(share_tab)
        sp.setContentsMargins(14, 12, 14, 12)
        sp.setSpacing(8)
        sht = QLabel("Shares (pool target — not a block reward)")
        sht.setObjectName("tagline")
        sht.setWordWrap(True)
        sp.addWidget(sht)

        share_detail = QFrame()
        share_detail.setObjectName("shareDetail")
        sg = QGridLayout(share_detail)
        sg.setContentsMargins(10, 8, 10, 8)
        sg.setHorizontalSpacing(12)
        sg.setVerticalSpacing(6)
        self.lbl_sh_count_k, self.lbl_sh_count = _stat_pair("Submitted")
        self.lbl_sh_acc_k, self.lbl_sh_acc = _stat_pair("Accepted / rejected")
        self.lbl_sh_nonce_k, self.lbl_sh_nonce = _stat_pair("Last nonce", mono=True)
        self.lbl_sh_status_k, self.lbl_sh_status = _stat_pair("Last status")
        self.lbl_sh_hash_k, self.lbl_sh_hash = _stat_pair("Last hash", mono=True)
        sh_pairs = [
            (self.lbl_sh_count_k, self.lbl_sh_count),
            (self.lbl_sh_acc_k, self.lbl_sh_acc),
            (self.lbl_sh_nonce_k, self.lbl_sh_nonce),
            (self.lbl_sh_status_k, self.lbl_sh_status),
        ]
        for i, (k, v) in enumerate(sh_pairs):
            r, c = divmod(i, 2)
            sg.addWidget(k, r * 2, c * 2)
            sg.addWidget(v, r * 2 + 1, c * 2, 1, 2)
        sg.addWidget(self.lbl_sh_hash_k, 4, 0)
        sg.addWidget(self.lbl_sh_hash, 5, 0, 1, 4)
        self.lbl_sh_hash.setMinimumHeight(36)
        sp.addWidget(share_detail)

        self.share_list = QTextEdit()
        self.share_list.setReadOnly(True)
        self.share_list.setMinimumHeight(100)
        self.share_list.setPlaceholderText("No shares yet.")
        self.share_list.setFont(QFont("Cascadia Mono", 10))
        sp.addWidget(self.share_list, 1)
        tabs.addTab(share_tab, "Shares")

        # --- Event log ---
        log_tab = QWidget()
        lp = QVBoxLayout(log_tab)
        lp.setContentsMargins(14, 12, 14, 12)
        lp.setSpacing(8)
        self.event_log = QTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setMinimumHeight(160)
        self.event_log.setPlaceholderText(
            "Jobs, shares, block candidates, and pool replies appear here."
        )
        self.event_log.setFont(QFont("Cascadia Mono", 10))
        lp.addWidget(self.event_log, 1)
        tabs.addTab(log_tab, "Event log")

        tabs.setCurrentIndex(0)  # Settings active by default
        layout.addWidget(tabs, 1)

        foot = QLabel(f"Settings file: {settings_file()}")
        foot.setObjectName("statKey")
        foot.setWordWrap(True)
        layout.addWidget(foot)

        self._addr_save_timer = QTimer(self)
        self._addr_save_timer.setSingleShot(True)
        self._addr_save_timer.timeout.connect(self._persist_form)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._push_settings)
        self._timer.start(1000)

        self.lbl_rate.setText("0 H/s")
        self.lbl_total.setText("0")
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
        settings_menu = self.menuBar().addMenu("&Settings")
        act_settings = QAction("Settings…", self)
        act_settings.triggered.connect(self._open_settings)
        settings_menu.addAction(act_settings)
        act_wiz = QAction("Run setup wizard again…", self)
        act_wiz.triggered.connect(self._rerun_setup_wizard)
        settings_menu.addAction(act_wiz)

        help_menu = self.menuBar().addMenu("&Help")
        act_how = QAction("How to Use…", self)
        act_how.triggered.connect(self._show_howto)
        help_menu.addAction(act_how)
        act_fb = QAction("Feedback / Suggestions…", self)
        act_fb.triggered.connect(self._show_feedback)
        help_menu.addAction(act_fb)
        act_upd = QAction("Check for Updates…", self)
        act_upd.triggered.connect(lambda: self._check_for_updates(manual=True))
        help_menu.addAction(act_upd)

        # Top-level Quit next to Help — full exit (not tray hide)
        act_quit_menu = QAction("&Quit", self)
        act_quit_menu.triggered.connect(self._quit_from_menu)
        self.menuBar().addAction(act_quit_menu)

    def _show_howto(self) -> None:
        from ui.howto_dialog import HowToUseDialog

        HowToUseDialog(self).exec()

    def _show_feedback(self) -> None:
        from ui.feedback_dialog import FeedbackDialog

        FeedbackDialog(self).exec()

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

    def _apply_idle_mining_ui(self) -> None:
        """Reset mining-page controls to idle (no auto-start)."""
        self.start_btn.setEnabled(bool(self._profile.mining_ready))
        self.stop_btn.setEnabled(False)
        self.address_edit.setEnabled(True)
        self.test_mode.setEnabled(True)
        self.btn_change_network.setEnabled(True)
        self.lbl_conn.setText("Not connected")
        self.lbl_status.setText("Ready — choose Start after selecting a network.")
        self.lbl_rate.setText("0 H/s")

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

    def _apply_network_to_ui(self) -> None:
        self._profile = get_profile(self._network_id)
        self.setWindowTitle(f"{APP_NAME} — {self._profile.display_name}")
        self.lbl_network_badge.setText(
            f"Network: {self._profile.display_name}  ·  {self._profile.algorithm}  ·  "
            f"{self._profile.stratum_host}:{self._profile.stratum_port}"
        )
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
        self.start_btn.setEnabled(
            ready and not blocked and not self.controller.is_running()
        )
        is_xmr = self._network_id == "xmr"
        is_managed = self._profile.engine_kind == "managed_external"
        # Native OpenCL counter not on XMR/RVN/ERG — avoid misleading label
        if is_managed:
            self.lbl_total_k.setText("Total attempts")
            self.lbl_total.setText("— (external engine)")
            self.lbl_work.setText(
                "External engine: see hash rate and share rows "
                "(OpenCL total attempts only on BTC/BCH)."
            )
        else:
            self.lbl_total_k.setText("Total attempts")
        if blocked:
            self.lbl_status.setText(blocked)
        elif not ready:
            self.lbl_status.setText(
                f"{self._profile.display_name} engine is not connected yet — see the note on network selection."
            )
        self._refresh_addr_hint()
        if is_xmr:
            self.lbl_job_k.setText("Current work (height/diff)")
            self.btn_stats.setText("Open rewards page")
            self.lbl_stats_hint.setText(
                "Open the Kryptex page for rewards (accepted = share, not a block). "
                "Work row shows height/diff from XMRig; no stratum job_id."
            )
        elif self._network_id == "bch":
            self.lbl_job_k.setText("Current job ID")
            self.btn_stats.setText("Open account page")
            self.lbl_stats_hint.setText(
                "2Miners home page does not list you; you need /account/bitcoincash:…. "
                "Without a first accepted share the site shows /search (mindiff ~32K — can take a while on GPU)."
            )
        else:
            self.lbl_job_k.setText("Current job ID")
            self.btn_stats.setText("Open pool page")
            self.lbl_stats_hint.setText(
                "Server stats may lag; with low hash rate / high mindiff they "
                "may not show up immediately."
            )
        preview = self._profile.stats_url_for(self.address_edit.text().strip())
        if preview:
            if is_xmr:
                self.lbl_stats_url.setText(
                    f"Rewards / account (Kryptex; accepted≠block): {preview}"
                )
            else:
                self.lbl_stats_url.setText(f"Stats: {preview}")
            self.btn_stats.setEnabled(True)
            self._stats_url = preview
        else:
            if is_xmr:
                self.lbl_stats_url.setText(
                    "Rewards / account: Kryptex link enables when you enter an XMR address"
                )
            else:
                self.lbl_stats_url.setText(
                    "Stats: enabled when address is set / network supports it"
                )
            self.btn_stats.setEnabled(False)
            self._stats_url = ""

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

    @contextmanager
    def _hold_mine_scroll(self) -> Iterator[None]:
        """Keep QScrollArea viewport still while focus/enable changes (Start/Stop)."""
        bar = self._mine_scroll.verticalScrollBar()
        hbar = self._mine_scroll.horizontalScrollBar()
        vpos, hpos = bar.value(), hbar.value()

        def _restore() -> None:
            bar.setValue(vpos)
            hbar.setValue(hpos)

        try:
            yield
        finally:
            _restore()
            QTimer.singleShot(0, _restore)

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
                "pause_temp": int(self._cfg.get("pause_temp") or 65),
                "resume_temp": int(self._cfg.get("resume_temp") or 55),
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
            }
        )
        self._cfg = load_settings()
        self._refresh_addr_hint()
        # Stats / rewards page preview
        preview = self._profile.stats_url_for(addr)
        if preview and not self.controller.is_running():
            if self._network_id == "xmr":
                self.lbl_stats_url.setText(
                    f"Rewards / account (Kryptex; accepted≠block): {preview}"
                )
                self.btn_stats.setText("Open rewards page")
            else:
                self.lbl_stats_url.setText(f"Stats: {preview}")
                self.btn_stats.setText("Open pool page")
            self.btn_stats.setEnabled(True)
            self._stats_url = preview
    def _intensity_val(self) -> int:
        return int(self._cfg.get("intensity") or 4)

    def _pause_temp_val(self) -> int:
        return int(self._cfg.get("pause_temp") or 65)

    def _resume_temp_val(self) -> int:
        return int(self._cfg.get("resume_temp") or 55)

    def _cpu_threads_val(self) -> int:
        return int(self._cfg.get("cpu_thread_limit") or 0)

    def _pause_battery_val(self) -> bool:
        return bool(self._cfg.get("pause_on_battery", True))

    def _push_settings(self) -> None:
        self.controller.update_settings(
            self._intensity_val(),
            self._pause_temp_val(),
            self._resume_temp_val(),
        )

    def _allow_mine_without_temp(self) -> bool:
        return bool(self._cfg.get("allow_mine_without_temp", False))

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
            self._on_start_inner()
        except Exception as exc:
            import traceback

            traceback.print_exc()
            QMessageBox.warning(
                self,
                "Could not start",
                f"Start failed unexpectedly:\n\n{exc}",
            )

    def _on_start_inner(self) -> None:
        self._persist_form()
        self._push_settings()
        blocked = network_block_reason(self._network_id, probe_gpu=True)
        if blocked:
            QMessageBox.warning(self, "Hardware / dependency", blocked)
            return
        if not self._profile.mining_ready:
            QMessageBox.information(
                self,
                "No engine",
                f"{self._profile.display_name} mining engine is not connected yet.\n"
                f"{self._profile.notes}",
            )
            return
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
            return
        if self._stop_busy:
            QMessageBox.information(
                self, "Stopping", "Cannot start a new session until stop finishes."
            )
            return

        if not self._ensure_external_miner_ready(on_ready=self._begin_mining_after_gates):
            return

        self._begin_mining_after_gates()

    def _begin_mining_after_gates(self) -> None:
        """Thermal gate + controller.start (after miner is ready)."""
        self._defender_help_shown = False

        from monitor.thermal_probe import probe_temperature_readable

        allow_no_temp = self._allow_mine_without_temp()
        temp_ok, temp_detail = probe_temperature_readable(
            self._network_id,
            gpu_bus_id=str(self._cfg.get("gpu_bus_id") or ""),
            gpu_uuid=str(self._cfg.get("gpu_uuid") or ""),
        )
        if not temp_ok and not allow_no_temp:
            if not self._confirm_mine_without_temp(temp_detail):
                return
            allow_no_temp = True
        if not temp_ok:
            self._refresh_thermal_unsafe_banner(running_without_temp=True)

        try:
            self.controller.update_cpu_options(
                cpu_thread_limit=self._cpu_threads_val(),
                pause_on_battery=self._pause_battery_val(),
                xmrig_donate_level=int(self._cfg.get("xmrig_donate_level") or 1),
            )
            self.controller.gpu_bus_id = str(self._cfg.get("gpu_bus_id") or "")
            self.controller.gpu_uuid = str(self._cfg.get("gpu_uuid") or "")
            self.controller.start(
                self.address_edit.text(),
                test_mode=self.test_mode.isChecked(),
                network_id=self._network_id,
                allow_mine_without_temp=allow_no_temp,
            )
        except Exception as exc:
            from engines.windows_security import looks_like_defender_block
            from ui.defender_help_dialog import show_defender_help

            if looks_like_defender_block(exc):
                label = "XMRig" if self._network_id == "xmr" else "Rigel"
                show_defender_help(self, label)
            else:
                QMessageBox.warning(self, "Could not start", str(exc))
            return
        with self._hold_mine_scroll():
            # Enable Stop first so focus does not jump past it into Status (scrolls down).
            self.stop_btn.setEnabled(True)
            self.start_btn.clearFocus()
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self.start_btn.setEnabled(False)
            self.address_edit.setEnabled(False)
            self.test_mode.setEnabled(False)
            self.btn_change_network.setEnabled(False)

    def _on_stop(self) -> None:
        def _after(ok: bool) -> None:
            if not ok:
                QMessageBox.warning(
                    self,
                    "Could not stop",
                    "Miner thread or process did not exit in time. "
                    "New session / network change blocked. Try Stop again.",
                )
                self.stop_btn.setEnabled(True)
                self.start_btn.setEnabled(False)
                return
            self.start_btn.setEnabled(self._profile.mining_ready)
            self.stop_btn.setEnabled(False)
            self.address_edit.setEnabled(True)
            self.test_mode.setEnabled(True)
            self.btn_change_network.setEnabled(True)
            self._persist_form()

        self._begin_async_stop(_after)

    def _sync_idle_controls_if_needed(self) -> None:
        """Unlock Start on natural session end (battery/process); do not touch on stop_failed."""
        if self._stop_busy:
            return
        if self.controller._stop_failed:
            return
        if self.controller.is_running():
            return
        # Not running but UI still looks busy — reset to idle
        if self.stop_btn.isEnabled() and not self.start_btn.isEnabled():
            self.start_btn.setEnabled(self._profile.mining_ready)
            self.stop_btn.setEnabled(False)
            self.address_edit.setEnabled(True)
            self.test_mode.setEnabled(True)
            self.btn_change_network.setEnabled(True)

    def _apply_stats(self, stats: MiningStats) -> None:
        try:
            self._apply_stats_inner(stats)
        except Exception:
            # Never let a UI stats tick kill the process (PyQt slot abort).
            import traceback

            traceback.print_exc()

    def _apply_stats_inner(self, stats: MiningStats) -> None:
        self._sync_idle_controls_if_needed()
        self.lbl_conn.setText(
            "TEST (local)"
            if stats.test_mode and stats.connected
            else ("Connected" if stats.connected else "Not connected")
        )
        self.lbl_device.setText(stats.device_name or "—")
        rate = stats.hashrate
        if rate >= 1_000_000:
            self.lbl_rate.setText(f"{rate / 1_000_000:.2f} MH/s")
        elif rate >= 1000:
            self.lbl_rate.setText(f"{rate / 1000:.2f} kH/s")
        else:
            self.lbl_rate.setText(f"{rate:.0f} H/s")
        managed = self._profile.engine_kind == "managed_external"
        if managed:
            self.lbl_total.setText("— (external engine)")
        else:
            self.lbl_total.setText(f"{stats.total_hashes:,}")
        self.lbl_time.setText(f"{stats.elapsed:.0f}s")
        self.lbl_shares.setText(f"accepted {stats.accepted} / rejected {stats.rejected}")
        self._update_scoreboard(
            int(getattr(stats, "block_candidate_count", 0) or 0),
            int(stats.accepted or 0),
            int(stats.rejected or 0),
            int(stats.total_hashes or 0),
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
        self.lbl_coinbase.setText(stats.coinbase_status or "—")
        if stats.block_store_error:
            self.lbl_coinbase.setText(
                (stats.coinbase_status or "") + f" | Store: {stats.block_store_error}"
            )
        if stats.ckpool_stats_url:
            if self._network_id == "xmr":
                self.lbl_stats_url.setText(
                    f"Rewards / account (Kryptex; accepted≠block): {stats.ckpool_stats_url}"
                )
                self.btn_stats.setText("Open rewards page")
            else:
                self.lbl_stats_url.setText(
                    f"Pool (check manually; accepted≠block): {stats.ckpool_stats_url}"
                )
                self.btn_stats.setText("Open pool page")
            self.btn_stats.setEnabled(True)
            self._stats_url = stats.ckpool_stats_url
        else:
            if self._network_id == "xmr":
                self.lbl_stats_url.setText(
                    "Rewards / account: Kryptex link enables when you enter an XMR address"
                )
            else:
                self.lbl_stats_url.setText(
                    "Pool stats: active when address set / network supports it"
                )
            self.btn_stats.setEnabled(False)
            self._stats_url = ""
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
            if not self._allow_mine_without_temp():
                self._refresh_thermal_unsafe_banner(running_without_temp=False)
        else:
            self._update_scoreboard_temp(None)
            if self.controller.allow_mine_without_temp or self._allow_mine_without_temp():
                self.lbl_temp.setText("unreadable · thermal protection OFF (unsafe)")
                self._refresh_thermal_unsafe_banner(running_without_temp=True)
            else:
                self.lbl_temp.setText("unreadable · start blocked unless override")
                self._refresh_thermal_unsafe_banner(running_without_temp=False)
        if managed:
            self.lbl_work.setText(
                f"External engine · rate={self.lbl_rate.text()} · "
                f"share accepted={stats.accepted} rejected={stats.rejected} · "
                f"{(stats.status or '')[:80]}"
            )
        elif stats.last_scanned:
            self.lbl_work.setText(
                f"scanned={stats.last_scanned:,}   "
                f"global={stats.last_global:,}  local={stats.last_local}   "
                f"kernel={stats.last_kernel_ms:.1f}ms   sleep={stats.last_sleep_s * 1000:.0f}ms"
            )
        else:
            self.lbl_work.setText("no kernel yet (connected ≠ hashing)")
        self.lbl_status.setText(stats.status)
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
        act_settings = QAction("Settings…", self)
        act_settings.triggered.connect(self._open_settings)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self._quit_app)
        act_how = QAction("How to Use…", self)
        act_how.triggered.connect(self._show_howto)
        act_fb = QAction("Feedback / Suggestions…", self)
        act_fb.triggered.connect(self._show_feedback)
        act_upd = QAction("Check for Updates…", self)
        act_upd.triggered.connect(lambda: self._check_for_updates(manual=True))
        self._act_show_scoreboard = QAction("Show scoreboard", self)
        self._act_show_scoreboard.triggered.connect(self._on_tray_show_scoreboard)
        menu.addAction(act_show)
        menu.addAction(act_hide)
        menu.addAction(act_settings)
        menu.addAction(self._act_show_scoreboard)
        menu.addSeparator()
        menu.addAction(act_how)
        menu.addAction(act_fb)
        menu.addAction(act_upd)
        menu.addSeparator()
        menu.addAction(act_quit)
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

    def _difficulty_row_visible(self) -> bool:
        return self._network_id in SUPPORTED_BEST_HASH_NETWORKS

    def _push_difficulty_row(self) -> None:
        vis = self._difficulty_row_visible()
        net, best = self._last_net_diff, self._last_best_diff
        self.scoreboard.set_difficulty_row(net, best, visible=vis)
        if self._scoreboard_overlay is not None:
            self._scoreboard_overlay.set_difficulty_row(net, best, visible=vis)

    def _load_stored_best_into_row(self) -> None:
        """Idle startup / network switch: show stored best for current network."""
        self._last_net_diff = None
        self._last_best_diff = None
        self._last_accepted_best_diff = None
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
            self._set_status_best_labels(
                gpu_live if gpu_live is not None else self._last_best_diff,
                acc_live if acc_live is not None else self._last_accepted_best_diff,
                visible=True,
            )
        else:
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

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._cfg, self)
        dlg.form.pick_gpu_clicked.connect(self._on_pick_gpu)
        if dlg.exec():
            vals = dlg.values()
            overlay = bool(vals.pop("scoreboard_overlay_enabled", True))
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
        """Menu-bar Quit: confirm, then full exit (same path as tray Quit)."""
        reply = QMessageBox.question(
            self,
            "Quit",
            "Quit Easy Block Finder 4000?\n\n"
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

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._quit_busy_host is not None and self._quit_busy_host.isVisible():
            self._quit_busy_host.setGeometry(self.rect())

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
                "Still running in the tray. Double-click to open; tray menu → Quit to exit.",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
