"""Tools → Mining Statistical Audit — Live histogram + Offline + Stratum Work Ledger."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app_meta import APP_NAME, APP_VERSION_LABEL, load_app_icon


def _format_report(title: str, data: dict[str, Any]) -> str:
    lines = [title, "=" * len(title), ""]
    for k, v in data.items():
        if k in ("band_evals", "focus_evals", "job_summaries") and isinstance(v, list):
            lines.append(f"{k}:")
            for row in v:
                lines.append(f"  {row}")
        elif k in ("gpu_best_timeline", "accepted_best_timeline", "notify_events"):
            lines.append(f"{k}: ({len(v) if isinstance(v, list) else v} entries)")
            if isinstance(v, list):
                for row in v[-8:]:
                    lines.append(f"  {row}")
        elif k == "histogram_counts":
            lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("")
    lines.append("--- raw JSON ---")
    lines.append(json.dumps(data, indent=2, default=str))
    return "\n".join(lines)


def _format_ledger_metrics(m: dict[str, Any]) -> str:
    src = str(m.get("measurement_source") or "")
    syn = bool(m.get("attempts_are_synthetic"))
    provenance = (
        "SYNTHETIC — NOT a GPU measurement"
        if syn or src == "synthetic_time_budget_not_gpu"
        else "GPU completed batches (result.scanned)"
    )
    lines = [
        "Stratum Work Ledger",
        "===================",
        "",
        f"Measurement source:          {provenance}",
        f"Total Attempts (GPU scanned):{m.get('total_attempts', 0):,}",
        f"Unique Attempts (intervals): {m.get('unique_attempts', m.get('estimated_unique_attempts', 0)):,}",
        f"Duplicate Attempts:          {m.get('duplicate_attempts', 0):,}",
        f"Duplicate Rate %:            {m.get('duplicate_rate_percent', 0):.4f}",
        f"Identical Work Notifications:{m.get('identical_work_notifications', 0)}",
        f"Reconnects:                  {m.get('reconnects', 0)}",
        f"Extranonce1 Changes:         {m.get('extranonce1_changes', 0)}",
        f"Jobs cut by new notify:      {m.get('jobs_cut_by_notify', 0)}",
        f"Hashes on cut jobs:          {m.get('hashes_completed_on_cut_jobs', 0):,}",
        f"Aborted in-flight (hits):    {m.get('aborted_inflight_batches', 0)}",
        f"Batches completed:           {m.get('batches_completed', 0)}",
        f"Jobs seen / notifies:        {m.get('jobs_seen', 0)} / {m.get('notify_count', 0)}",
        f"Ledger overhead vs kernel %: {m.get('ledger_overhead_pct_of_kernel', 0):.4f}",
        f"Hashrate mean (H/s):         {m.get('hashrate_mean', 0):,.0f}",
        "",
        "GPU Best timeline (last 8):",
    ]
    for row in (m.get("gpu_best_timeline") or [])[-8:]:
        lines.append(f"  {row}")
    lines.append("Accepted Best timeline (last 8):")
    for row in (m.get("accepted_best_timeline") or [])[-8:]:
        lines.append(f"  {row}")
    lines.append("")
    lines.append(
        "Note: Identical Work Notifications alone are not errors; "
        "Duplicate Attempts = re-scanned nonce space from completed GPU intervals "
        "(incl. partial overlaps). Synthetic/time-budget exports are labeled separately."
    )
    return "\n".join(lines)


class MiningAuditDialog(QDialog):
    def __init__(
        self,
        *,
        live_enabled: bool,
        get_live_snapshot: Callable[[], Optional[dict]],
        set_live_enabled: Callable[[bool], None],
        ledger_enabled: bool = False,
        get_ledger_metrics: Callable[[], Optional[dict]] | None = None,
        get_ledger_export: Callable[..., Optional[dict]] | None = None,
        set_ledger_enabled: Callable[[bool], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_live = get_live_snapshot
        self._set_live = set_live_enabled
        self._get_ledger = get_ledger_metrics or (lambda: None)
        self._get_ledger_export = get_ledger_export or (lambda mask=True: None)
        self._set_ledger = set_ledger_enabled or (lambda _on: None)
        self.setWindowTitle(f"Mining Statistical Audit — {APP_NAME}")
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.setMinimumSize(680, 560)

        lay = QVBoxLayout(self)
        title = QLabel("Mining Statistical Audit")
        title.setFont(QFont("Bahnschrift", 14, QFont.Weight.Bold))
        lay.addWidget(title)
        note = QLabel(
            f"{APP_VERSION_LABEL} — Default OFF. "
            "Work Ledger does not use the audit histogram kernel (minimal overhead). "
            "Live Pool Audit (histogram) is separate and optional. "
            "Exported ledger reports mask wallet / extranonce / coinbase by default."
        )
        note.setWordWrap(True)
        lay.addWidget(note)

        self.chk_ledger = QCheckBox(
            "Enable Stratum Work Ledger (notify / duplicate search-space)"
        )
        self.chk_ledger.setChecked(bool(ledger_enabled))
        self.chk_ledger.toggled.connect(self._on_ledger_toggled)
        lay.addWidget(self.chk_ledger)

        self.chk_live = QCheckBox(
            "Enable Live Pool Audit histogram (BTC/BCH — uses sha256d_audit.cl)"
        )
        self.chk_live.setChecked(bool(live_enabled))
        self.chk_live.toggled.connect(self._on_live_toggled)
        lay.addWidget(self.chk_live)

        row = QHBoxLayout()
        row.addWidget(QLabel("Offline hashes:"))
        self.spin_n = QSpinBox()
        self.spin_n.setRange(1024, 16_777_216)
        self.spin_n.setValue(65536)
        self.spin_n.setSingleStep(1024)
        row.addWidget(self.spin_n)
        self.btn_offline = QPushButton("Run Offline Engine Audit")
        self.btn_offline.clicked.connect(self._run_offline)
        row.addWidget(self.btn_offline)
        self.btn_ledger = QPushButton("Refresh Work Ledger")
        self.btn_ledger.clicked.connect(self._refresh_ledger)
        row.addWidget(self.btn_ledger)
        self.btn_refresh = QPushButton("Refresh Live Histogram")
        self.btn_refresh.clicked.connect(self._refresh_live)
        row.addWidget(self.btn_refresh)
        row.addStretch(1)
        lay.addLayout(row)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Cascadia Mono", 10))
        lay.addWidget(self.view, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
            | QDialogButtonBox.StandardButton.Save
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setText("Copy / export masked JSON")
            save_btn.clicked.connect(self._copy_export)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        if ledger_enabled:
            self._refresh_ledger()
        else:
            self.view.setPlainText(
                "Stratum Work Ledger is OFF (recommended default).\n"
                "Enable it, mine BTC on Public Pool 20–30+ minutes, then Refresh.\n"
                "Identical-work notifies are counted separately from Duplicate Attempts."
            )

    def _on_ledger_toggled(self, on: bool) -> None:
        self._set_ledger(bool(on))
        if on:
            self._refresh_ledger()
        else:
            self.view.setPlainText("Stratum Work Ledger disabled.")

    def _on_live_toggled(self, on: bool) -> None:
        self._set_live(bool(on))
        if on:
            self._refresh_live()
        else:
            self.view.appendPlainText("\n(Live histogram audit disabled.)")

    def _refresh_ledger(self) -> None:
        m = self._get_ledger()
        if not m:
            self.view.setPlainText(
                "Work Ledger enabled but no data yet — start BTC mining / wait for notify."
            )
            return
        self.view.setPlainText(_format_ledger_metrics(m))

    def _refresh_live(self) -> None:
        snap = self._get_live()
        if not snap:
            self.view.setPlainText(
                "Live histogram audit enabled but no snapshot yet "
                "(BTC/BCH mining with audit kernel)."
            )
            return
        self.view.setPlainText(_format_report("Live Pool Audit snapshot", snap))

    def _run_offline(self) -> None:
        self.btn_offline.setEnabled(False)
        self.view.setPlainText("Running Offline Engine Audit…")
        try:
            from audit.offline_runner import run_offline_engine_audit

            report = run_offline_engine_audit(
                total_hashes=int(self.spin_n.value()),
                batch_size=min(8192, int(self.spin_n.value())),
                measure_overhead=True,
            )
            self.view.setPlainText(
                _format_report("Offline Engine Audit", report.to_dict())
            )
            if report.status == "skipped":
                QMessageBox.information(self, "Skipped / untested", report.message)
        except Exception as exc:
            self.view.setPlainText(f"Offline audit error: {exc}")
        finally:
            self.btn_offline.setEnabled(True)

    def _copy_export(self) -> None:
        data = self._get_ledger_export(True)
        if data:
            text = json.dumps(data, indent=2, default=str)
            self.view.setPlainText(text)
        self.view.selectAll()
        self.view.copy()
