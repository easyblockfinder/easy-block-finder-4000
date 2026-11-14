"""Startup network picker — one network at a time."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app_meta import APP_NAME, APP_VERSION_LABEL, load_app_logo_pixmap
from networks.profiles import NetworkProfile, list_profiles


class NetworkSelectPage(QWidget):
    network_chosen = pyqtSignal(str)

    def __init__(
        self,
        selected_id: str = "btc",
        parent: QWidget | None = None,
        *,
        blocked: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("root")
        self._blocked = dict(blocked or {})
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        logo_pix = load_app_logo_pixmap(480, 110)
        brand = QLabel()
        brand.setObjectName("brand")
        if not logo_pix.isNull():
            brand.setPixmap(logo_pix)
            brand.setMinimumHeight(80)
        else:
            brand.setText(APP_NAME)
            brand.setFont(QFont("Bahnschrift", 28, QFont.Weight.Bold))
        layout.addWidget(brand)

        ver = QLabel(APP_VERSION_LABEL)
        ver.setObjectName("tagline")
        layout.addWidget(ver)

        title = QLabel("Choose network")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        sub = QLabel(
            "One network at a time. Accepted shares are not payouts. "
            "External engine fees (XMRig/Rigel) are shown separately. "
            f"{APP_NAME} does not redirect mining to donations — use Donate to support."
        )
        sub.setObjectName("tagline")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        panel = QFrame()
        panel.setObjectName("panel")
        p_layout = QVBoxLayout(panel)
        p_layout.setContentsMargins(14, 12, 14, 12)
        p_layout.setSpacing(8)

        self._group = QButtonGroup(self)
        self._radios: dict[str, QRadioButton] = {}
        for prof in list_profiles():
            row = self._make_row(prof)
            p_layout.addWidget(row)

        layout.addWidget(panel)

        self._hint = QLabel("")
        self._hint.setObjectName("tagline")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self.btn_continue = QPushButton("Continue")
        self.btn_continue.setObjectName("startBtn")
        self.btn_continue.clicked.connect(self._emit_choice)
        layout.addWidget(self.btn_continue)
        layout.addStretch(1)

        sid = selected_id if selected_id in self._radios else "btc"
        if self._blocked.get(sid):
            # Fall back to first available network
            sid = next(
                (nid for nid, r in self._radios.items() if r.isEnabled()),
                "xmr",
            )
        self._radios[sid].setChecked(True)
        self._refresh_hint()
        self._group.buttonClicked.connect(lambda _b: self._refresh_hint())

    def _make_row(self, prof: NetworkProfile) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(2)
        block = self._blocked.get(prof.id)
        if block:
            ready = "no hardware"
        elif prof.mining_ready:
            ready = "ready"
        else:
            ready = "engine in a later release"
        text = (
            f"{prof.display_name}  ·  {prof.algorithm}  ·  {prof.hardware_hint}  ·  {ready}"
        )
        radio = QRadioButton(text)
        radio.setProperty("network_id", prof.id)
        if block:
            radio.setEnabled(False)
            radio.setToolTip(block)
        self._group.addButton(radio)
        self._radios[prof.id] = radio
        v.addWidget(radio)
        detail = QLabel(
            f"{prof.stratum_host}:{prof.stratum_port}  |  "
            f"pool: {prof.pool_fee_note}  |  engine: {prof.engine_fee_note}"
            + (f"\n⛔ {block}" if block else "")
        )
        detail.setObjectName("statKey")
        detail.setWordWrap(True)
        v.addWidget(detail)
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
            self._hint.setText(block)
            self.btn_continue.setEnabled(False)
            return
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
