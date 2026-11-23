"""Settings dialog — machine-wide options (not per-coin address)."""

from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.machine_settings import MachineSettingsForm

_SECTION_CSS = (
    "QFrame#settingsSection {"
    "  background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;"
    "}"
)


def _section_card(title: str, hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("settingsSection")
    card.setStyleSheet(_SECTION_CSS)
    outer = QVBoxLayout(card)
    outer.setContentsMargins(12, 10, 12, 12)
    outer.setSpacing(8)
    head = QLabel(title)
    head.setObjectName("sectionTitle")
    outer.addWidget(head)
    if hint:
        note = QLabel(hint)
        note.setObjectName("tagline")
        note.setWordWrap(True)
        outer.addWidget(note)
    body = QVBoxLayout()
    body.setSpacing(8)
    outer.addLayout(body)
    return card, body


class SettingsDialog(QDialog):
    def __init__(
        self,
        cfg: dict[str, Any],
        parent=None,
        *,
        on_reset_records: Optional[Callable[[], None]] = None,
        network_id: str = "btc",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings — Easy Block Finder 4000")
        self.setMinimumWidth(480)
        self.setMinimumHeight(560)
        self.resize(520, 640)
        self._cfg = dict(cfg)
        self._on_reset_records = on_reset_records
        self._network_id = (network_id or "btc").strip().lower()
        self._records_reset = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        title = QLabel("Settings")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        note = QLabel(
            "Machine-wide options. Payout address stays on the mining screen."
        )
        note.setObjectName("tagline")
        note.setWordWrap(True)
        root.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        root.addWidget(scroll, 1)

        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(12)

        self.form = MachineSettingsForm()
        self.form.load_from(self._cfg)
        lay.addWidget(self.form)

        disp, dbody = _section_card("Display")
        self.chk_scoreboard = QCheckBox("Mini scoreboard when minimized to tray")
        self.chk_scoreboard.setChecked(
            bool(self._cfg.get("scoreboard_overlay_enabled", True))
        )
        dbody.addWidget(self.chk_scoreboard)
        lay.addWidget(disp)

        rec, rbody = _section_card(
            "Personal best records",
            "Clears saved GPU Best and Accepted Best on this PC. "
            "Does not reset session share counters.",
        )
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_reset_records = QPushButton("Reset records…")
        self.btn_reset_records.setToolTip(
            "Delete GPU BEST / ACC BEST for the current network or all networks."
        )
        self.btn_reset_records.clicked.connect(self._reset_records)
        row.addWidget(self.btn_reset_records, 0)
        row.addStretch(1)
        rbody.addLayout(row)
        self.lbl_reset_status = QLabel("")
        self.lbl_reset_status.setObjectName("tagline")
        self.lbl_reset_status.setWordWrap(True)
        self.lbl_reset_status.setVisible(False)
        rbody.addWidget(self.lbl_reset_status)
        lay.addWidget(rec)

        lay.addStretch(1)

        from ui.wheel_guard import harden_wheel_widgets

        harden_wheel_widgets(self)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _reset_records(self) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Reset records")
        box.setText("Clear personal best hash records?")
        box.setInformativeText(
            "Removes saved GPU Best and Accepted Best values.\n"
            "Mining session counters (accepted/rejected shares) stay intact."
        )
        btn_net = box.addButton(
            f"This network ({self._network_id.upper()})",
            QMessageBox.ButtonRole.AcceptRole,
        )
        btn_all = box.addButton(
            "All networks", QMessageBox.ButtonRole.DestructiveRole
        )
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None or clicked == box.button(QMessageBox.StandardButton.Cancel):
            return
        try:
            from mining.best_hash_store import clear_best_hash_records

            if clicked is btn_all:
                clear_best_hash_records(network_id=None)
                scope = "all networks"
            else:
                clear_best_hash_records(network_id=self._network_id)
                scope = self._network_id.upper()
            self._records_reset = True
            self.lbl_reset_status.setText(f"Records cleared ({scope}).")
            self.lbl_reset_status.setVisible(True)
            if self._on_reset_records is not None:
                self._on_reset_records()
        except Exception as exc:
            QMessageBox.warning(
                self, "Reset records", f"Could not clear records:\n{exc}"
            )

    def values(self) -> dict[str, Any]:
        out = self.form.values()
        out["scoreboard_overlay_enabled"] = self.chk_scoreboard.isChecked()
        return out

    @property
    def records_were_reset(self) -> bool:
        return bool(self._records_reset)
