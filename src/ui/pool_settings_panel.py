"""Per-network mining pool selection (default / preset / custom)."""

from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from networks.pool_input import (
    parse_port,
    sanitize_host,
    validate_password,
    validate_username_format,
    validate_worker,
)
from networks.pool_presets import list_presets
from networks.pool_resolve import normalize_pool_by_network, reset_pool_selection, resolve_pool
from networks.profiles import get_profile


_KIND_LABELS = {
    "solo": "SOLO — full block reward path (when pool pays that way)",
    "shared": "SHARED — proportional shares; not a solo block lottery",
    "unknown": "UNKNOWN — payout not classified; verify manually",
}


class PoolSettingsPanel(QWidget):
    """Embeddable pool picker. Call load_network / save into settings dict."""

    def __init__(
        self,
        *,
        is_running: Callable[[], bool],
        request_stop: Callable[[], None],
        get_wallet: Optional[Callable[[], str]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._is_running = is_running
        self._request_stop = request_stop
        self._get_wallet = get_wallet or (lambda: "")
        self.on_applied: Optional[Callable[[dict[str, Any]], None]] = None
        self._network_id = "btc"
        self._pool_by_network: dict[str, Any] = {}
        self._loading = False
        self._testing = False

        self.setStyleSheet(
            """
            QLabel#betaBadge {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #d97706, stop:0.55 #c2410c, stop:1 #9a3412
                );
                color: #fff7ed;
                font-family: "Segoe UI", "Cascadia Mono", sans-serif;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 1.4px;
                padding: 3px 10px;
                border-radius: 10px;
                border: 1px solid #7c2d12;
            }
            QLabel#betaBadgeHint {
                color: #9a3412;
                font-size: 11px;
                font-weight: 600;
            }
            """
        )

        box = QGroupBox("Connection")
        box.setObjectName("poolGroup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(box)
        lay = QVBoxLayout(box)
        lay.setSpacing(10)
        lay.setContentsMargins(4, 8, 4, 4)

        self.lbl_current = QLabel("")
        self.lbl_current.setObjectName("statKey")
        self.lbl_current.setWordWrap(True)
        lay.addWidget(self.lbl_current)

        self.lbl_kind = QLabel("")
        self.lbl_kind.setWordWrap(True)
        self.lbl_kind.setStyleSheet("font-weight: 700; padding: 2px 0;")
        lay.addWidget(self.lbl_kind)

        self.lbl_banner = QLabel("")
        self.lbl_banner.setObjectName("tagline")
        self.lbl_banner.setWordWrap(True)
        self.lbl_banner.setVisible(False)
        lay.addWidget(self.lbl_banner)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.mode = QComboBox()
        self.mode.addItem("Default (built-in)", "default")
        self.mode.addItem("Preset (verified list)", "preset")
        self.mode.addItem("Custom · BETA", "custom")
        self.mode.currentIndexChanged.connect(self._on_mode_changed)

        mode_wrap = QWidget()
        mode_row = QHBoxLayout(mode_wrap)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(8)
        mode_row.addWidget(self.mode, 1)
        self.lbl_beta = QLabel("BETA")
        self.lbl_beta.setObjectName("betaBadge")
        self.lbl_beta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_beta.setToolTip(
            "Custom Mining Pool is in beta. Verify host, TLS, username format, "
            "and payouts on the pool site yourself."
        )
        self.lbl_beta.setVisible(False)
        mode_row.addWidget(self.lbl_beta, 0, Qt.AlignmentFlag.AlignVCenter)
        form.addRow("Mode", mode_wrap)

        self.preset = QComboBox()
        self.preset.currentIndexChanged.connect(self._refresh_preview)
        form.addRow("Preset", self.preset)

        self.host = QLineEdit()
        self.host.setPlaceholderText("pool.example.com")
        self.host.editingFinished.connect(self._refresh_preview)
        form.addRow("Host", self.host)

        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(3333)
        self.port.valueChanged.connect(lambda _=None: self._refresh_preview())
        form.addRow("Port", self.port)

        self.transport = QComboBox()
        self.transport.addItem("TCP (cleartext)", "tcp")
        self.transport.addItem("TLS (certificate verified)", "tls")
        self.transport.currentIndexChanged.connect(self._refresh_preview)
        form.addRow("Transport", self.transport)

        self.user_fmt = QComboBox()
        for fmt, label in (
            ("{wallet}", "{wallet}"),
            ("{wallet}.{worker}", "{wallet}.{worker}"),
            ("solo:{wallet}", "solo:{wallet}"),
        ):
            self.user_fmt.addItem(label, fmt)
        self.user_fmt.currentIndexChanged.connect(self._refresh_preview)
        form.addRow("Username format", self.user_fmt)

        self.worker = QLineEdit()
        self.worker.setPlaceholderText("optional worker name")
        self.worker.editingFinished.connect(self._refresh_preview)
        form.addRow("Worker", self.worker)

        self.password = QLineEdit()
        self.password.setText("x")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password", self.password)

        self.pool_kind = QComboBox()
        self.pool_kind.addItem("SOLO", "solo")
        self.pool_kind.addItem("SHARED", "shared")
        self.pool_kind.addItem("UNKNOWN", "unknown")
        self.pool_kind.currentIndexChanged.connect(self._refresh_preview)
        form.addRow("Pool kind", self.pool_kind)

        lay.addLayout(form)

        self.lbl_beta_hint = QLabel(
            "Custom Mining Pool · BETA — connection works; payouts and stats "
            "pages are not verified for every host."
        )
        self.lbl_beta_hint.setObjectName("betaBadgeHint")
        self.lbl_beta_hint.setWordWrap(True)
        self.lbl_beta_hint.setVisible(False)
        lay.addWidget(self.lbl_beta_hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_apply = QPushButton("Apply pool")
        self.btn_apply.setObjectName("tabActionBtn")
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_reset = QPushButton("Reset to default")
        self.btn_reset.setObjectName("tabActionBtn")
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_test = QPushButton("Test connection")
        self.btn_test.setObjectName("tabActionBtn")
        self.btn_test.setToolTip(
            "Requires a real mining.notify/job. TCP or authorize alone is not enough."
        )
        self.btn_test.clicked.connect(self._on_test)
        row.addWidget(self.btn_apply)
        row.addWidget(self.btn_reset)
        row.addWidget(self.btn_test)
        row.addStretch(1)
        lay.addLayout(row)

        self.lbl_test = QLabel("")
        self.lbl_test.setObjectName("tagline")
        self.lbl_test.setWordWrap(True)
        lay.addWidget(self.lbl_test)

        hint = QLabel(
            "Changing pool while mining requires Stop first. "
            "Best-hash records stay per coin and are not reset. "
            "Shared pools never imply a solo block reward."
        )
        hint.setObjectName("tagline")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._set_custom_visible(False)
        from ui.wheel_guard import harden_wheel_widgets

        harden_wheel_widgets(self)

    def load_network(self, network_id: str, pool_by_network: dict[str, Any]) -> None:
        self._network_id = network_id
        self._pool_by_network = normalize_pool_by_network(pool_by_network or {})
        self._loading = True
        try:
            prof = get_profile(network_id)
            # Preset/custom for all mining-ready engines (native + managed external).
            ready = bool(prof.mining_ready)
            self.mode.setEnabled(ready)
            self.btn_apply.setEnabled(ready)
            self.btn_reset.setEnabled(ready)
            self.btn_test.setEnabled(ready)
            self._reload_presets()
            sel = self._pool_by_network.get(network_id) or {}
            mode = str(sel.get("mode") or "default") if ready else "default"
            idx = self.mode.findData(mode)
            self.mode.setCurrentIndex(idx if idx >= 0 else 0)
            if mode == "preset":
                pid = str(sel.get("preset_id") or "")
                pidx = self.preset.findData(pid)
                self.preset.setCurrentIndex(pidx if pidx >= 0 else 0)
                self.worker.setText(str(sel.get("worker") or ""))
            elif mode == "custom":
                custom = sel.get("custom") if isinstance(sel.get("custom"), dict) else {}
                self.host.setText(str(custom.get("host") or ""))
                try:
                    self.port.setValue(int(custom.get("port") or 3333))
                except (TypeError, ValueError):
                    self.port.setValue(3333)
                tidx = self.transport.findData(str(custom.get("transport") or "tcp"))
                self.transport.setCurrentIndex(tidx if tidx >= 0 else 0)
                fidx = self.user_fmt.findData(str(custom.get("username_format") or "{wallet}"))
                self.user_fmt.setCurrentIndex(fidx if fidx >= 0 else 0)
                self.worker.setText(str(custom.get("worker") or ""))
                self.password.setText(str(custom.get("password") if custom.get("password") is not None else "x"))
                kidx = self.pool_kind.findData(str(custom.get("pool_kind") or "unknown"))
                self.pool_kind.setCurrentIndex(kidx if kidx >= 0 else 2)
            else:
                self.host.setText(prof.stratum_host)
                self.port.setValue(int(prof.stratum_port))
                self.password.setText(prof.password or "x")
            self._on_mode_changed()
            self._refresh_preview()
        finally:
            self._loading = False

    def pool_by_network(self) -> dict[str, Any]:
        return dict(self._pool_by_network)

    def _reload_presets(self) -> None:
        self.preset.blockSignals(True)
        self.preset.clear()
        presets = list_presets(self._network_id)
        if not presets:
            self.preset.addItem("(no verified presets for this coin yet)", "")
        else:
            for p in presets:
                self.preset.addItem(f"{p.display_name} — {p.host}:{p.port}", p.id)
        self.preset.blockSignals(False)

    def _set_custom_visible(self, on: bool) -> None:
        for w in (
            self.host,
            self.port,
            self.transport,
            self.user_fmt,
            self.password,
            self.pool_kind,
        ):
            w.setEnabled(on)
        # Worker usable for preset + custom
        mode = self.mode.currentData()
        self.worker.setEnabled(mode in ("preset", "custom"))
        self.preset.setEnabled(mode == "preset")
        self.lbl_beta.setVisible(bool(on))
        self.lbl_beta_hint.setVisible(bool(on))

    def _on_mode_changed(self) -> None:
        mode = self.mode.currentData()
        self._set_custom_visible(mode == "custom")
        if not self._loading:
            self._refresh_preview()

    def _draft_selection(self) -> dict[str, Any]:
        mode = str(self.mode.currentData() or "default")
        if mode == "default":
            return {"mode": "default"}
        if mode == "preset":
            pid = str(self.preset.currentData() or "").strip()
            entry: dict[str, Any] = {"mode": "preset", "preset_id": pid}
            worker = self.worker.text().strip()
            if worker:
                entry["worker"] = worker
            return entry
        return {
            "mode": "custom",
            "custom": {
                "host": self.host.text().strip(),
                "port": int(self.port.value()),
                "transport": str(self.transport.currentData() or "tcp"),
                "username_format": str(self.user_fmt.currentData() or "{wallet}"),
                "worker": self.worker.text().strip(),
                "password": self.password.text(),
                "pool_kind": str(self.pool_kind.currentData() or "unknown"),
            },
        }

    def _refresh_preview(self) -> None:
        draft = {self._network_id: self._draft_selection()}
        try:
            ep = resolve_pool(self._network_id, draft)
        except Exception:
            ep = resolve_pool(self._network_id, {})
        kind = ep.pool_kind
        self.lbl_current.setText(
            f"Active resolution: {ep.display_name} · {ep.host}:{ep.port} · {ep.transport.upper()}"
        )
        self.lbl_kind.setText(f"Pool kind: {kind.upper()} — {_KIND_LABELS.get(kind, '')}")
        color = {"solo": "#2e7d32", "shared": "#ef6c00", "unknown": "#c62828"}.get(kind, "#333")
        self.lbl_kind.setStyleSheet(f"color: {color}; font-weight: 700; padding: 2px 0;")
        from networks.pool_validation import get_validation_profile

        vp = get_validation_profile(ep.validation_profile_id)
        if vp.payout_unverified_banner and vp.banner_text:
            self.lbl_banner.setText(vp.banner_text)
            self.lbl_banner.setVisible(True)
        elif kind == "shared":
            self.lbl_banner.setText(_KIND_LABELS["shared"])
            self.lbl_banner.setVisible(True)
        else:
            self.lbl_banner.setVisible(False)

    def _ensure_stopped(self) -> bool:
        if not self._is_running():
            return True
        ans = QMessageBox.question(
            self,
            "Stop mining first",
            "Pool changes apply on the next Start. Stop mining now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return False
        self._request_stop()
        return not self._is_running()

    def _on_apply(self) -> None:
        if not self._ensure_stopped():
            return
        mode = str(self.mode.currentData() or "default")
        if mode == "preset" and not str(self.preset.currentData() or "").strip():
            QMessageBox.warning(self, "No preset", "No verified preset is available for this coin.")
            return
        if mode == "custom":
            try:
                sanitize_host(self.host.text())
                parse_port(self.port.value())
                validate_username_format(str(self.user_fmt.currentData() or "{wallet}"))
                validate_worker(self.worker.text())
                validate_password(self.password.text())
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid pool settings", str(exc))
                return
        entry = self._draft_selection()
        if mode == "default":
            self._pool_by_network = reset_pool_selection(
                self._network_id, self._pool_by_network
            )
        else:
            merged = dict(self._pool_by_network)
            merged[self._network_id] = entry
            self._pool_by_network = normalize_pool_by_network(merged)
        self._refresh_preview()
        if callable(self.on_applied):
            self.on_applied(self._pool_by_network)

    def _on_reset(self) -> None:
        if not self._ensure_stopped():
            return
        self._pool_by_network = reset_pool_selection(
            self._network_id, self._pool_by_network
        )
        self.load_network(self._network_id, self._pool_by_network)
        if callable(self.on_applied):
            self.on_applied(self._pool_by_network)

    def _on_test(self) -> None:
        if self._testing:
            return
        wallet = (self._get_wallet() or "").strip()
        if not wallet:
            QMessageBox.warning(
                self,
                "Address required",
                "Enter a payout address first — the pool test must authorize as that user.",
            )
            return
        draft = {self._network_id: self._draft_selection()}
        try:
            ep = resolve_pool(self._network_id, draft)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid pool", str(exc))
            return
        from networks.profiles import get_profile

        prof = get_profile(self._network_id)
        username = ep.render_username(prof.pool_identity(wallet))
        self._testing = True
        self.btn_test.setEnabled(False)
        self.lbl_test.setText(
            f"Testing {ep.host}:{ep.port} (job required; temporary processes will stop)…"
        )
        try:
            result = self._run_pool_probe(prof, ep, username)
        finally:
            self._testing = False
            self.btn_test.setEnabled(True)
        self.lbl_test.setText(result.message)
        if result.ok:
            QMessageBox.information(self, "Pool connection OK", result.message)
        else:
            QMessageBox.warning(self, "Pool connection failed", result.message)

    def _run_pool_probe(self, prof, ep, username: str):
        from networks.pool_connection_test import (
            PoolConnectionTestResult,
            probe_native_pool_connection,
        )

        if prof.engine_kind == "native_sha256d":
            return probe_native_pool_connection(
                host=ep.host,
                port=ep.port,
                username=username,
                password=ep.password,
                transport=ep.transport,
                timeout_s=20.0,
            )
        if prof.engine_kind != "managed_external":
            return PoolConnectionTestResult(
                ok=False,
                stage="failed",
                message=f"Unsupported engine for pool test: {prof.engine_kind}",
            )
        try:
            from engines.fetch_miner import ensure_miner
        except Exception as exc:
            return PoolConnectionTestResult(
                ok=False, stage="failed", message=f"Miner toolkit unavailable: {exc}"
            )
        if self._network_id == "xmr":
            try:
                exe = ensure_miner("xmrig", reverify=False)
            except Exception as exc:
                return PoolConnectionTestResult(
                    ok=False, stage="failed", message=f"XMRig not available: {exc}"
                )
            from engines.external_pool_probe import probe_xmrig_pool

            return probe_xmrig_pool(
                exe=exe,
                host=ep.host,
                port=ep.port,
                username=username,
                password=ep.password,
                transport=ep.transport,
                timeout_s=35.0,
            )
        if self._network_id in ("rvn", "erg"):
            try:
                exe = ensure_miner("rigel", reverify=False)
            except Exception as exc:
                return PoolConnectionTestResult(
                    ok=False, stage="failed", message=f"Rigel not available: {exc}"
                )
            from engines.external_pool_probe import probe_rigel_pool

            algo = "kawpow" if self._network_id == "rvn" else "autolykos2"
            coin = self._network_id
            return probe_rigel_pool(
                exe=exe,
                algorithm=algo,
                coin=coin,
                host=ep.host,
                port=ep.port,
                username=username,
                password=ep.password,
                transport=ep.transport,
                timeout_s=45.0,
            )
        return PoolConnectionTestResult(
            ok=False,
            stage="failed",
            message=f"No external pool probe wired for {self._network_id}.",
        )
