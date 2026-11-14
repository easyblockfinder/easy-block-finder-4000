"""Startup network picker — one network at a time."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app_meta import APP_NAME, APP_VERSION_LABEL, load_app_logo_pixmap
from networks.profiles import NetworkProfile, list_profiles


def _short_block_reason(block: str) -> str:
    """Keep UI readable; full text stays in tooltip."""
    text = " ".join((block or "").split())
    if len(text) <= 140:
        return text
    # Prefer the leading “disabled — …” sentence
    for sep in (". Insufficient", ". free=", " — free="):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
            break
    if len(text) > 140:
        text = text[:137].rstrip() + "…"
    return text


class NetworkSelectPage(QWidget):
    network_chosen = pyqtSignal(str)
    hardware_check_clicked = pyqtSignal()

    def __init__(
        self,
        selected_id: str = "btc",
        parent: QWidget | None = None,
        *,
        blocked: dict[str, str] | None = None,
        subtitle: str | None = None,
        show_hardware_button: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("root")
        self._blocked = {k: v for k, v in (blocked or {}).items() if v}
        self._selected_pref = selected_id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        logo_pix = load_app_logo_pixmap(440, 88)
        brand = QLabel()
        brand.setObjectName("brand")
        if not logo_pix.isNull():
            brand.setPixmap(logo_pix)
            brand.setMinimumHeight(64)
        else:
            brand.setText(APP_NAME)
            brand.setFont(QFont("Bahnschrift", 28, QFont.Weight.Bold))
        layout.addWidget(brand)

        ver = QLabel(APP_VERSION_LABEL)
        ver.setObjectName("tagline")
        layout.addWidget(ver)

        self._title = QLabel("Choose network")
        self._title.setObjectName("sectionTitle")
        layout.addWidget(self._title)

        self._sub = QLabel(
            subtitle
            or (
                "Choose a network to continue. Optional: run a hardware / VRAM check "
                "before selecting GPU coins. Accepted shares are not payouts. "
                f"{APP_NAME} does not redirect mining to donations — use Donate to support."
            )
        )
        self._sub.setObjectName("tagline")
        self._sub.setWordWrap(True)
        layout.addWidget(self._sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(scroll, 1)

        self._panel = QFrame()
        self._panel.setObjectName("panel")
        self._panel_layout = QVBoxLayout(self._panel)
        self._panel_layout.setContentsMargins(14, 12, 14, 12)
        self._panel_layout.setSpacing(10)

        self._group = QButtonGroup(self)
        self._radios: dict[str, QRadioButton] = {}
        self._detail_labels: dict[str, QLabel] = {}
        self._rebuild_rows()
        scroll.setWidget(self._panel)

        self._hint = QLabel("")
        self._hint.setObjectName("tagline")
        self._hint.setWordWrap(True)
        self._hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addWidget(self._hint)

        self.btn_continue = QPushButton("Continue")
        self.btn_continue.setObjectName("startBtn")
        self.btn_continue.clicked.connect(self._emit_choice)
        layout.addWidget(self.btn_continue)

        self.btn_hardware = QPushButton("Check hardware / GPU capacity…")
        self.btn_hardware.clicked.connect(self.hardware_check_clicked.emit)
        self.btn_hardware.setVisible(show_hardware_button)
        layout.addWidget(self.btn_hardware)

        self._apply_default_selection()
        self._refresh_hint()
        self._group.buttonClicked.connect(lambda _b: self._refresh_hint())

    def apply_blocks(self, blocked: dict[str, str | None]) -> None:
        """Refresh enable/disable + reasons after a capacity probe."""
        self._blocked = {k: v for k, v in blocked.items() if v}
        self._rebuild_rows()
        self._apply_default_selection()
        self._refresh_hint()

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.btn_continue.setEnabled(
            not busy and not self._blocked.get(self._selected_id())
        )
        self.btn_hardware.setEnabled(not busy)
        if busy:
            self._hint.setText(message or "Checking GPU capacity…")
        elif not busy and message:
            self._hint.setText(message)

    def _rebuild_rows(self) -> None:
        while self._panel_layout.count():
            item = self._panel_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for radio in list(self._radios.values()):
            self._group.removeButton(radio)
        self._radios.clear()
        self._detail_labels.clear()
        for prof in list_profiles():
            self._panel_layout.addWidget(self._make_row(prof))
        self._panel_layout.addStretch(1)

    def _apply_default_selection(self) -> None:
        sid = self._selected_pref if self._selected_pref in self._radios else "btc"
        if self._blocked.get(sid) or sid not in self._radios:
            sid = next(
                (nid for nid, r in self._radios.items() if r.isEnabled()),
                "xmr",
            )
        if sid in self._radios:
            self._radios[sid].setChecked(True)

    def _make_row(self, prof: NetworkProfile) -> QWidget:
        wrap = QWidget()
        wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 4, 0, 8)
        v.setSpacing(4)

        block = self._blocked.get(prof.id)
        if block:
            low = block.lower()
            if "vram" in low or "insufficient" in low or "dag" in low or "dataset" in low:
                ready = "insufficient VRAM"
            else:
                ready = "hardware unavailable"
        elif prof.mining_ready:
            ready = "ready"
        else:
            ready = "engine in a later release"

        radio = QRadioButton(f"{prof.display_name}  ·  {ready}")
        radio.setProperty("network_id", prof.id)
        radio.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        if block:
            radio.setEnabled(False)
            radio.setToolTip(block)
        self._group.addButton(radio)
        self._radios[prof.id] = radio
        v.addWidget(radio)

        meta = QLabel(
            f"{prof.algorithm}  ·  {prof.hardware_hint}\n"
            f"{prof.stratum_host}:{prof.stratum_port}  |  "
            f"pool: {prof.pool_fee_note}  |  engine: {prof.engine_fee_note}"
        )
        meta.setObjectName("statKey")
        meta.setWordWrap(True)
        meta.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        v.addWidget(meta)

        if block:
            warn = QLabel(f"⛔ {_short_block_reason(block)}")
            warn.setWordWrap(True)
            warn.setToolTip(block)
            warn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            warn.setStyleSheet("color: #b71c1c;")
            v.addWidget(warn)
            self._detail_labels[prof.id] = warn

        return wrap

    def _selected_id(self) -> str:
        for nid, radio in self._radios.items():
            if radio.isChecked():
                return nid
        return "btc"

    def _refresh_hint(self) -> None:
        from networks.profiles import get_profile

        nid = self._selected_id()
        block = self._blocked.get(nid)
        if block:
            self._hint.setText(_short_block_reason(block))
            self._hint.setToolTip(block)
            self.btn_continue.setEnabled(False)
            return
        self._hint.setToolTip("")
        self.btn_continue.setEnabled(True)
        prof = get_profile(nid)
        if prof.mining_ready:
            self._hint.setText(prof.notes or "You can continue mining on this network.")
        else:
            self._hint.setText(
                f"{prof.display_name} can be selected; Start is disabled for now "
                f"({prof.notes or 'engine not connected yet'})."
            )

    def _emit_choice(self) -> None:
        nid = self._selected_id()
        if self._blocked.get(nid):
            return
        self.network_chosen.emit(nid)
