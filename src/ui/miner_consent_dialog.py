"""First-run / on-demand consent before downloading official miners."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from engines.miner_catalog import consent_body_for_miners, get_miner_info


class MinerDownloadConsentDialog(QDialog):
    """
    Consent + optional per-miner selection.
    When selectable=True, checkboxes let the user pick which missing miners to fetch.
    """

    def __init__(
        self,
        miner_ids: list[str],
        parent=None,
        *,
        selectable: bool = False,
        precheck_all: bool = True,
        title: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Miner download consent")
        self.setMinimumSize(560, 460)
        self._checks: dict[str, QCheckBox] = {}
        root = QVBoxLayout(self)

        title_lbl = QLabel(
            title or "Allow download of official mining engines?"
        )
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet("font-weight: 700; font-size: 14px;")
        root.addWidget(title_lbl)

        hint_lbl = QLabel(
            hint
            or (
                "Only engines you allow will be downloaded. "
                "Nothing is installed into the app zip; files go to your AppData folder "
                "after SHA-256 verification."
            )
        )
        hint_lbl.setWordWrap(True)
        root.addWidget(hint_lbl)

        if selectable:
            pick = QLabel("Select engines to download now:")
            pick.setStyleSheet("font-weight: 600;")
            root.addWidget(pick)
            for mid in miner_ids:
                try:
                    info = get_miner_info(mid)
                    label = f"{info.display_name} {info.version}  ({', '.join(n.upper() for n in info.networks)})"
                except Exception:
                    label = mid
                cb = QCheckBox(label)
                cb.setChecked(bool(precheck_all))
                self._checks[mid] = cb
                root.addWidget(cb)
        else:
            self._fixed_ids = list(miner_ids)

        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText(consent_body_for_miners(miner_ids))
        body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        root.addWidget(body, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Allow download")
        buttons.button(QDialogButtonBox.StandardButton.No).setText("Not now")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._selectable = selectable
        if not selectable:
            self._fixed_ids = list(miner_ids)

    def _on_accept(self) -> None:
        if self._selectable and not self.selected_miner_ids():
            QMessageBox.information(
                self,
                "Nothing selected",
                "Tick at least one engine to download, or choose Not now.",
            )
            return
        self.accept()

    def selected_miner_ids(self) -> list[str]:
        if self._selectable:
            return [mid for mid, cb in self._checks.items() if cb.isChecked()]
        return list(getattr(self, "_fixed_ids", []))


def ask_miner_download_consent(parent, miner_ids: list[str]) -> bool:
    dlg = MinerDownloadConsentDialog(miner_ids, parent)
    return dlg.exec() == QDialog.DialogCode.Accepted


def ask_startup_miner_download(
    parent, missing_ids: list[str]
) -> list[str] | None:
    """
    First-launch offer for missing miners.
    Returns selected miner ids, or None if user declined / closed.
    """
    if not missing_ids:
        return []
    dlg = MinerDownloadConsentDialog(
        missing_ids,
        parent,
        selectable=True,
        precheck_all=True,
        title="Official miners are not installed yet",
        hint=(
            "XMRig (Monero) and/or Rigel (Ravencoin / Ergo) are missing. "
            "Checked engines will download from the official release and be SHA-256 verified. "
            "You can skip and download later when you press Start on that network."
        ),
    )
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return dlg.selected_miner_ids()
