"""Mining orchestration: Stratum + OpenCL GPU + temperature + CPU verification."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional

from app_meta import APP_NAME
from mining.app_donation import (
    default_app_donation,
    donation_address_for,
    in_donation_slice,
    is_effectively_enabled,
    normalize_app_donation,
)
from mining.managed_counters import ManagedShareAccum
from mining.bitcoin import (
    midstate_from_header,
    nonce_to_submit_hex,
    validate_address_for_network,
)
from mining.best_hash import (
    SUPPORTED_BEST_HASH_NETWORKS,
    difficulty_from_hash_int,
    hash_be_hex_to_int,
    is_better_hash,
    network_difficulty_from_nbits,
    verify_best_candidate,
)
from mining.best_hash_store import (
    BestHashLoadError,
    BestHashRecord,
    load_best_hash_state,
    quarantine_corrupt_store,
    upsert_record_if_better,
)
from mining.lifetime_stats import add_lifetime_attempts, get_lifetime_attempts
from monitor.user_activity import idle_seconds
from networks.pool_input import safe_pool_log_fields
from networks.pool_resolve import resolve_pool
from networks.pool_types import ResolvedPoolEndpoint
from networks.pool_validation import get_validation_profile
from worker.idle_policy import IdleMiningPolicy, IdlePolicyState
from worker.work_scale import (
    adaptive_duty_sleep,
    intensity_batch_sleep,
    update_ema,
)
from mining.block_store import (
    STATUS_CANDIDATE,
    STATUS_ORPHAN,
    STATUS_PENDING_VERIFY,
    STATUS_POOL,
    STATUS_TEST,
    BlockCandidateStore,
    ExplorerTracker,
)
from mining.coinbase import verify_job_coinbase_payout
from mining.job import MiningJob, WorkBatch, job_from_notify
from monitor.temp import GpuTemperatureMonitor
from networks.profiles import NetworkProfile, get_profile
from stratum.client import StratumClient
from worker.hashrate import rate_from_window

log = logging.getLogger(__name__)

_INTENSITY = {
    1: (1_048_576, 0.008),
    2: (1_048_576, 0.005),
    3: (2_097_152, 0.004),
    4: (2_097_152, 0.002),
    5: (4_194_304, 0.002),
    6: (4_194_304, 0.001),
    7: (8_388_608, 0.001),
    8: (8_388_608, 0.0),
    9: (16_777_216, 0.0),
    10: (33_554_432, 0.0),
}


@dataclass
class MiningStats:
    connected: bool = False
    status: str = "Ready"
    hashrate: float = 0.0
    total_hashes: int = 0  # session attempts (reset each start)
    lifetime_attempts: int = 0  # per-network lifetime (persisted)
    elapsed: float = 0.0
    accepted: int = 0
    rejected: int = 0
    difficulty: float = 0.0
    gpu_temp: Optional[int] = None
    temp_readable: bool = False
    paused_thermal: bool = False
    test_mode: bool = False
    block_candidates: list[dict] = field(default_factory=list)
    share_events: list[dict] = field(default_factory=list)
    event_log: list[str] = field(default_factory=list)
    device_name: str = ""
    last_batch: int = 0
    last_scanned: int = 0
    last_global: int = 0
    last_local: int = 0
    last_sleep_s: float = 0.0
    last_kernel_ms: float = 0.0
    block_candidate_count: int = 0
    share_submit_count: int = 0
    last_block: Optional[dict] = None
    last_share: Optional[dict] = None
    current_job_id: str = ""
    server_difficulty: Optional[float] = None
    suggest_difficulty_sent: Optional[float] = 1.0
    submit_rpc_log: list[dict] = field(default_factory=list)
    stratum_wire_log: list[dict] = field(default_factory=list)
    ckpool_stats_url: str = ""
    payout_address: str = ""
    pending_difficulty: Optional[float] = None
    coinbase_status: str = ""
    block_store_error: str = ""
    session_id: int = 0
    engine_fee_shares: int = 0
    unattributed_shares: int = 0
    app_donation_shares: int = 0
    donation_active: bool = False
    thermal_source: str = ""
    network_id: str = "btc"
    network_difficulty: Optional[float] = None
    best_difficulty: Optional[float] = None  # GPU batch personal best
    best_hash_be_hex: Optional[str] = None
    best_record_broken: bool = False  # one-shot UI edge; cleared after emit
    accepted_best_difficulty: Optional[float] = None
    accepted_best_hash_be_hex: Optional[str] = None
    accepted_record_broken: bool = False  # one-shot Status celebration
    last_accepted_difficulty: Optional[float] = None  # session: latest ACC hash diff
    best_hash_mode: str = "gpu_batch"
    pool_display: str = ""
    pool_kind: str = "solo"
    pool_mode: str = "default"
    pool_banner: str = ""
    activity_mode: str = "off"  # off | active | idle (auto-idle feature)
    activity_scale: float = 1.0  # 0..1 of configured capacity
    paused_idle: bool = False
    activity_ui: str = ""  # human Status text (no fake hashrate %)
    search_strategy: str = "sequential"  # sequential | reverse | randomized
    session_kind: str = "auto"  # auto | game
    game_event: str = ""
    game_event_detail: str = ""
    game_board_id: str = ""
    game_tiles_revealed: int = 0
    game_tile_update: Optional[dict] = None
    game_metrics: dict = field(default_factory=dict)
    game_board_index: int = 0
    game_board_count: int = 0
    game_board_reload: bool = False  # UI: repaint tiles from active board


class MiningController:
    def __init__(self, on_stats: Optional[Callable[[MiningStats], None]] = None) -> None:
        self.on_stats = on_stats
        self.stats = MiningStats()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._job_lock = threading.Lock()
        self._job: Optional[MiningJob] = None
        self._job_gen = 0
        self._stratum: Optional[StratumClient] = None
        self._gpu = None
        self._temp = GpuTemperatureMonitor()
        self.stats.temp_readable = self._temp.available
        self._pending_difficulty: float = 1.0
        self._pending_submits: dict[tuple[int, int], dict] = {}
        self._submit_lock = threading.Lock()
        self._block_store = BlockCandidateStore()
        self._explorer = ExplorerTracker(on_update=self._on_explorer_update)
        self._coinbase_ok = True
        # clean=true / oturum de i iminde artar t m eski batch'ler ge ersiz
        self._work_epoch: int = 1
        self._known_jobs: list[MiningJob] = []

        self.intensity = 1
        self.pause_temp = 75
        self.resume_temp = 60
        self.address = ""
        self.test_mode = False
        self.network_id = "btc"
        self._profile: NetworkProfile = get_profile("btc")
        self._best_mode_cache: Optional[str] = None
        self._best_broken_pending = False
        self._accepted_broken_pending = False
        # In-memory bests for the active network (loaded once per start/switch).
        self._best_record: Optional[BestHashRecord] = None  # GPU best
        self._accepted_best_record: Optional[BestHashRecord] = None
        self._best_store_ok = True  # False after load failure → skip writes
        self._pool_endpoint: Optional[ResolvedPoolEndpoint] = None
        self._start_time = 0.0
        self._hash_window: list[tuple[float, float, int]] = []
        self._paused = False
        self._xmrig = None
        self._rigel = None
        self.cpu_thread_limit = 0
        self.pause_on_battery = True
        self.xmrig_donate_level = 1
        self.gpu_bus_id: str = ""
        self.gpu_uuid: str = ""
        self.allow_mine_without_temp: bool = False  # legacy flag; never honored
        self._thermal_unreadable_logged = False
        self.app_donation: dict[str, Any] = default_app_donation()
        self._donation_active: bool = False
        self._mining_address: str = ""
        self._resolved_gpu_bus: str = ""
        self._session_gen: int = 0
        self._stop_failed: bool = False
        self._preparing: bool = False
        self._run_session: int = 0
        self._lifecycle_lock = threading.Lock()
        # Motor start/stop/fold: miner thread ile UI stop serile tirir.
        # stop() thread join s ras nda bu kilidi TUTMAZ (deadlock yok).
        self._motor_ops = threading.RLock()
        self._stopping: bool = False
        self._share_accum: Optional[ManagedShareAccum] = None
        self._motor_gen: int = 0
        self._idle_policy = IdleMiningPolicy()
        self._idle_force_active = False
        self._idle_scale = 1.0
        self._xmrig_idle_paused = False
        self._rigel_idle_paused = False
        self._ema_batch_s: float | None = None
        self._activity_ui: str = ""  # honest Status label for auto-idle
        # Live Pool Statistical Audit (None = OFF — production search kernel only)
        self._audit_live = None
        # Stratum Work Ledger (None = OFF — independent of histogram audit)
        self._work_ledger = None
        # Mining search strategy — locked for the session at start()
        self._search_strategy = "sequential"
        self._search_strategy_locked = False
        # Scratch Game Mode + optional concurrent auto (GPU time-share)
        self._session_kind = "auto"  # auto | game | both
        self._auto_enabled = False
        self._game_enabled = False
        # Board UI open → Game may take GPU; closed → Intensity 100% Auto.
        self._game_board_open = False
        self._auto_gpu_s = 0.0
        self._game_gpu_s = 0.0
        self._scratch = None
        self._game_boards: list = []
        self._game_board_index = -1
        self._game_wake = threading.Event()
        self._game_prevhash: Optional[str] = None
        self._game_active_tile_id: Optional[int] = None
        self._game_board_gen = 0
        self._game_board_reload_pending = False
        self._game_boards_lock = threading.RLock()
        # Session-wide completed tiles (survives EN2 switches / board history trim).
        self._game_tiles_completed_session = 0

    def set_search_strategy(self, strategy: str) -> None:
        """Set strategy only when not in an active locked session."""
        from mining.search_strategy import SearchStrategy, StrategySessionPolicy

        raw = (strategy or "sequential").strip().lower()
        try:
            strat = SearchStrategy(raw)
        except ValueError:
            strat = SearchStrategy.SEQUENTIAL
        pol = StrategySessionPolicy(
            SearchStrategy(self._search_strategy),
            locked=bool(self._search_strategy_locked),
        )
        if not pol.allow_change(strat, new_session=not self._search_strategy_locked):
            return
        self._search_strategy = strat.value

    def search_strategy(self) -> str:
        return str(self._search_strategy or "sequential")

    def set_live_audit(self, enabled: bool) -> None:
        """Enable/disable Live Pool Audit observer. OFF → no audit kernel, no hooks."""
        if enabled:
            if self._audit_live is None:
                from audit.live_observer import LiveAuditObserver

                self._audit_live = LiveAuditObserver()
        else:
            self._audit_live = None

    def live_audit_snapshot(self) -> Optional[dict]:
        if self._audit_live is None:
            return None
        from dataclasses import asdict

        return asdict(self._audit_live.snapshot())

    def set_work_ledger(self, enabled: bool) -> None:
        """Enable/disable Stratum Work Ledger (no kernel / allocation changes)."""
        if enabled:
            if self._work_ledger is None:
                from audit.work_ledger import StratumWorkLedger

                self._work_ledger = StratumWorkLedger()
        else:
            self._work_ledger = None

    def work_ledger_metrics(self) -> Optional[dict]:
        if self._work_ledger is None:
            return None
        return self._work_ledger.metrics()

    def work_ledger_export(self, *, mask: bool = True) -> Optional[dict]:
        if self._work_ledger is None:
            return None
        return self._work_ledger.export_dict(mask=mask)

    def update_settings(self, intensity: int, pause_temp: int, resume_temp: int) -> None:
        self.intensity = max(1, min(10, int(intensity)))
        self.pause_temp = int(pause_temp)
        self.resume_temp = int(resume_temp)

    def update_idle_options(
        self,
        *,
        enabled: bool = False,
        timeout_s: int = 150,
        active_pct: int = 10,
        idle_pct: int = 100,
        arm_session: bool = False,
    ) -> None:
        self._idle_policy.configure(
            enabled=enabled,
            timeout_s=timeout_s,
            active_pct=active_pct,
            idle_pct=idle_pct,
        )
        if not enabled:
            self.stats.activity_mode = "off"
            self.stats.activity_scale = 1.0
            self.stats.paused_idle = False
        elif arm_session:
            self._idle_policy.arm_session()

    def force_idle_active(self) -> None:
        """Sleep/session resume: treat as ACTIVE and reset idle timeout clock."""
        self._idle_force_active = True
        self._idle_policy.reset_to_active()

    def _eval_idle_policy(self) -> IdlePolicyState:
        force = bool(self._idle_force_active)
        if force:
            self._idle_force_active = False
        idle_s = idle_seconds() if self._idle_policy.enabled else None
        state = self._idle_policy.evaluate(idle_s=idle_s, force_active=force)
        self.stats.activity_mode = state.mode
        self.stats.activity_scale = float(state.scale)
        # paused_idle applied by engine adapters when scale==0 and not thermal/stopped
        return state

    def _set_activity_ui(self, text: str) -> None:
        self._activity_ui = text or ""
        self.stats.activity_ui = self._activity_ui

    def _interruptible_wait(
        self,
        total_s: float,
        *,
        chunk_s: float = 0.05,
        abort_if_active: bool = False,
    ) -> bool:
        """
        Wait up to total_s in small slices. Returns False if stopped or
        (when abort_if_active) user returned to Using-PC during an AFK duty wait.
        """
        remaining = max(0.0, float(total_s))
        while remaining > 1e-6:
            if self._stop.is_set():
                return False
            if abort_if_active and self._idle_policy.enabled:
                # Re-sample so long AFK duty waits end ASAP when the user returns.
                probe = self._idle_policy.evaluate(
                    idle_s=idle_seconds(), force_active=False
                )
                if probe.mode == "active":
                    self.stats.activity_mode = probe.mode
                    self.stats.activity_scale = float(probe.scale)
                    return False
            step = min(chunk_s, remaining)
            self._stop.wait(step)
            remaining -= step
        return not self._stop.is_set()

    def update_cpu_options(
        self,
        *,
        cpu_thread_limit: int = 0,
        pause_on_battery: bool = True,
        xmrig_donate_level: int = 1,
    ) -> None:
        import os

        n = os.cpu_count() or 1
        lim = int(cpu_thread_limit)
        if lim < 0 or lim > n:
            raise ValueError(f"cpu_thread_limit must be 0…{n} (0=auto).")
        self.cpu_thread_limit = lim
        self.pause_on_battery = bool(pause_on_battery)
        self.xmrig_donate_level = max(0, min(99, int(xmrig_donate_level)))

    def update_app_donation(self, cfg: dict[str, Any] | None) -> None:
        self.app_donation = normalize_app_donation(cfg or {})

    def is_running(self) -> bool:
        if self._stopping or self._preparing:
            return True
        if self._thread is not None and self._thread.is_alive():
            return True
        if self._stop_failed:
            return True
        if self._xmrig is not None and self._xmrig.is_running():
            return True
        if self._rigel is not None and self._rigel.is_running():
            return True
        return False

    def _stop_external(self, runner: Any, label: str, timeout_s: float = 6.0) -> Optional[BaseException]:
        """External miner stop; on failure keep reference and return exception."""
        if runner is None:
            return None
        try:
            runner.stop(timeout_s=timeout_s)
            return None
        except BaseException as exc:
            log.exception("%s stop", label)
            return exc

    def _retire_motor_into(
        self, accum: ManagedShareAccum, runner: Any, generation: int
    ) -> None:
        """Son API poll → callback kapat → snapshot → bir kez fold."""
        with self._motor_ops:
            if runner is not None and hasattr(runner, "refresh_snapshot"):
                try:
                    runner.refresh_snapshot()
                except Exception:
                    log.exception("refresh_snapshot")
            if runner is not None and hasattr(runner, "retire"):
                runner.retire()
            final = None
            if runner is not None and hasattr(runner, "take_final_snapshot"):
                try:
                    final = runner.take_final_snapshot()
                except Exception:
                    log.exception("take_final_snapshot")
            accum.retire_with_final(generation, final)

    def _fold_active_motor_shares(self) -> None:
        """UI / external stop: fold once before clearing refs."""
        with self._motor_ops:
            accum = self._share_accum
            if accum is None:
                return
            runner = self._xmrig if self._xmrig is not None else self._rigel
            # RLock: _retire_motor_into ayn ops kilidini yeniden al r
            if runner is not None and hasattr(runner, "refresh_snapshot"):
                try:
                    runner.refresh_snapshot()
                except Exception:
                    log.exception("refresh_snapshot")
            if runner is not None and hasattr(runner, "retire"):
                runner.retire()
            final = None
            if runner is not None and hasattr(runner, "take_final_snapshot"):
                try:
                    final = runner.take_final_snapshot()
                except Exception:
                    log.exception("take_final_snapshot")
            accum.set_donation_active(self._donation_active)
            accum.retire_with_final(self._motor_gen, final)
            self.stats.accepted = accum.display_accepted
            self.stats.app_donation_shares = accum.display_donation
            self.stats.engine_fee_shares = accum.display_fee
            self.stats.unattributed_shares = accum.display_unattr
            self.stats.rejected = accum.display_rejected

    def _motor_start_blocked(self) -> bool:
        """Block new motor start while stop was requested."""
        return self._stopping or self._stop.is_set()

    def _session_alive(self, session: int) -> bool:
        return session == self._session_gen and not self._stop.is_set()

    def _abort_if_temp_required(self) -> bool:
        """
        Temperature must be readable — no override. Returns True → abort start.
        """
        if self.stats.temp_readable:
            return False
        self.stats.status = (
            "Blocked: temperature unreadable — thermal protection is mandatory. "
            "Fix sensors/NVML before mining."
        )
        self._log_event(self.stats.status)
        self._emit()
        return True

    def poll_temperature(self) -> Optional[int]:
        """
        Always-on temperature sample for UI (and idle display).
        Does not start mining. Prefer selected GPU bus when set.
        """
        temp: Optional[int] = None
        src = ""
        profile = self._profile
        thermal = getattr(profile, "thermal_source", "") if profile else ""
        if thermal == "cpu" or (self.network_id or "").lower() == "xmr":
            try:
                from monitor.cpu_temp import CpuTemperatureMonitor

                mon = CpuTemperatureMonitor()
                temp = mon.read_celsius()
                src = mon.source_name
            except Exception as exc:
                src = f"CPU temp error: {exc}"
        else:
            bus = (self._resolved_gpu_bus or self.gpu_bus_id or "").strip()
            if bus:
                try:
                    from monitor.gpu_devices import temperature_for_bus

                    temp, src = temperature_for_bus(bus)
                except Exception as exc:
                    src = f"NVML error: {exc}"
                    temp = None
            else:
                temp = self._temp.read_celsius()
                src = "NVML (default GPU)" if temp is not None else (
                    self.stats.thermal_source or "NVML"
                )
        self.stats.gpu_temp = temp
        self.stats.temp_readable = temp is not None
        if src:
            self.stats.thermal_source = src
        return temp

    def start(
        self,
        address: str,
        test_mode: bool = False,
        *,
        network_id: str = "btc",
        allow_mine_without_temp: bool = False,
        pool_endpoint: ResolvedPoolEndpoint | None = None,
        pool_by_network: dict | None = None,
        session_kind: str = "auto",
    ) -> None:
        profile = get_profile(network_id)
        kind = (session_kind or "auto").strip().lower()
        if kind not in ("auto", "game"):
            raise ValueError(f"Unknown session_kind: {session_kind}")
        if kind == "game":
            if profile.id != "btc" or profile.engine_kind != "native_sha256d":
                raise ValueError("Game Mode requires BTC native OpenCL.")
        if not profile.mining_ready:
            raise ValueError(
                f"{profile.display_name} engine not ready yet: {profile.notes}"
            )
        if profile.engine_kind == "managed_external" and profile.id not in (
            "xmr",
            "rvn",
            "erg",
        ):
            raise ValueError(
                f"{profile.display_name} managed engine is not wired yet."
            )
        if profile.engine_kind not in ("native_sha256d", "managed_external"):
            raise ValueError(f"Unknown engine kind: {profile.engine_kind}")
            # stop() ile TOCTOU yok lifecycle alt nda guard + thread start
        # Attach second workload to a live native session (Auto ↔ Game).
        if (
            self._thread is not None
            and self._thread.is_alive()
            and not self._stopping
            and not self._stop_failed
            and self._profile.engine_kind == "native_sha256d"
            and profile.engine_kind == "native_sha256d"
            and self.network_id == profile.id
        ):
            self._attach_session_kind(kind)
            return

        if not self._lifecycle_lock.acquire(blocking=False):
            raise RuntimeError("Stop in progress — cannot start until it finishes.")
        try:
            if self._xmrig is not None and self._xmrig.is_running():
                raise RuntimeError(
                    "Previous XMRig process still running — wait for stop before starting."
                )
            if self._rigel is not None and self._rigel.is_running():
                raise RuntimeError(
                    "Previous Rigel process still running — wait for stop before starting."
                )
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError(
                    "Previous mining session still running — wait for stop before starting."
                )
            if self._stop_failed:
                raise RuntimeError(
                    "Previous stop failed (thread/process did not exit). "
                    "Restart the app or try Stop again."
                )
            if self._stopping:
                raise RuntimeError("Stop in progress — cannot start until it finishes.")
            if self.is_running():
                raise RuntimeError("Already running.")
            ok, err = validate_address_for_network(profile.id, address)
            if not ok:
                raise ValueError(err)

            self._profile = profile
            self.network_id = profile.id
            self.address = address.strip()
            self._mining_address = self.address
            self._donation_active = False
            self.test_mode = test_mode
            # Thermal guard is mandatory — ignore any override flag.
            self.allow_mine_without_temp = False
            _ = allow_mine_without_temp  # API compat; never honored
            self._auto_enabled = kind == "auto"
            self._game_enabled = kind == "game"
            self._game_board_open = False
            self._auto_gpu_s = 0.0
            self._game_gpu_s = 0.0
            self._refresh_session_kind()
            self._scratch = None
            self._game_boards = []
            self._game_board_index = -1
            self._game_wake.clear()
            self._game_prevhash = None
            self._game_active_tile_id = None
            self._game_board_reload_pending = False
            self._game_tiles_completed_session = 0
            # Lock search strategy for this session (BTC/BCH native only meaningful)
            if profile.engine_kind == "native_sha256d":
                self._search_strategy_locked = True
            else:
                self._search_strategy = "sequential"
                self._search_strategy_locked = False
            ep = pool_endpoint or resolve_pool(profile.id, pool_by_network)
            self._pool_endpoint = ep
            # Ba etkinse adres do rula
            if is_effectively_enabled(self.app_donation, profile.id):
                daddr = donation_address_for(self.app_donation, profile.id)
                dok, derr = validate_address_for_network(profile.id, daddr)
                if not dok:
                    raise ValueError(f"Donation address invalid: {derr}")
            from networks.pool_resolve import stats_url_for_endpoint

            # Selected pool only — custom/unknown with no template stay blank.
            stats_url = stats_url_for_endpoint(ep, self.address)
            self._explorer.configure(
                status_url=profile.explorer_status_url,
                block_url=profile.explorer_block_url,
                kind=profile.explorer_kind or "none",
            )
            lifetime = get_lifetime_attempts(profile.id)
            vprof_start = get_validation_profile(ep.validation_profile_id)
            pool_banner = ""
            if ep.mode != "default" and vprof_start.payout_unverified_banner:
                pool_banner = vprof_start.banner_text or ""
            elif ep.pool_kind == "shared":
                pool_banner = get_validation_profile("shared_pool").banner_text
            kind_label = str(ep.pool_kind or "unknown").upper()
            raw_loaded = (
                []
                if test_mode
                else self._block_store.load(
                    network_id=profile.id, include_unknown=True
                )
            )
            # Diskten gelen ge mi imdi bulundu bildirimi / acil uyar tetiklemesin
            loaded: list[dict] = []
            for rec in raw_loaded:
                item = dict(rec)
                item["loaded_from_disk"] = True
                # Belirsiz (unknown) a ezme UI da g r ns n, explorer a gitmesin
                if not str(item.get("network_id") or "").strip():
                    item["network_id"] = profile.id
                loaded.append(item)
                # Kullan c listesine ba kay tlar n kar t rma
            user_loaded = [r for r in loaded if not r.get("app_donation")]
            self._resolved_gpu_bus = ""
            thermal_src = ""
            if profile.thermal_source == "gpu_nvidia":
                thermal_src = "NVML (PCI bus/UUID)"
            self.stats = MiningStats(
                temp_readable=self._temp.available,
                test_mode=test_mode,
                status="Starting…",
                ckpool_stats_url=stats_url,
                payout_address=self.address,
                suggest_difficulty_sent=1.0,
                block_candidates=list(user_loaded)[:50],
                block_candidate_count=len(user_loaded),
                last_block=dict(user_loaded[0]) if user_loaded else None,
                block_store_error=self._block_store.last_error or "",
                network_id=profile.id,
                thermal_source=thermal_src,
                engine_fee_shares=0,
                unattributed_shares=0,
                app_donation_shares=0,
                donation_active=False,
                lifetime_attempts=lifetime,
                pool_display=ep.display_name or f"{ep.host}:{ep.port}",
                pool_kind=ep.pool_kind,
                pool_mode=ep.mode,
                pool_banner=pool_banner,
                coinbase_status=pool_banner
                or (f"Pool kind: {kind_label}" if ep.mode != "default" else ""),
                session_kind=self._session_kind,
            )
            self._best_broken_pending = False
            self._best_mode_cache = None
            self._load_best_into_stats(profile.id)
            if self._game_enabled and not self._auto_enabled:
                # Game-only: never arm Idle duty-cycle hashing.
                self.update_idle_options(enabled=False)
            # Yeni oturum eski thread i yeniden etkinle tirme
            self._session_gen += 1
            session = self._session_gen
            self._run_session = session
            self._stop.clear()
            self._stop_failed = False
            self._preparing = True
            self._paused = False
            self._job = None
            self._job_gen = 0
            self._pending_difficulty = 1.0
            self._coinbase_ok = True
            self._work_epoch = 1
            self._known_jobs = []
            with self._submit_lock:
                self._pending_submits.clear()
            self._block_store.ensure_writer()
            self._start_time = time.time()
            self._hash_window.clear()
            if not test_mode:
                for rec in loaded:
                    if rec.get("chain_status") not in (
                        "ana_zincirde_dogrulandi",
                        STATUS_TEST,
                    ):
                        self._explorer.watch(rec)

            def _entry() -> None:
                try:
                    self._run(session)
                finally:
                    self._preparing = False

            self._thread = threading.Thread(target=_entry, name="miner-main", daemon=True)
            self._thread.start()
        finally:
            self._lifecycle_lock.release()

    def stop(self) -> bool:
        """
        True if fully stopped. False on timeout/process; refs kept, new start blocked.
        start/stop serialized under lifecycle lock; overlapping stops wait/no-op.
        Join does not hold _motor_ops (no miner-thread deadlock).
        """
        with self._lifecycle_lock:
            self._stopping = True
            try:
                self._stop.set()
                self._preparing = False
                try:
                    self._explorer.stop()
                except Exception:
                    log.exception("explorer stop")
                if self._explorer.is_running():
                    # HTTP probe as l kalabilir madenci oturumunu kilitleme
                    log.warning(
                        "Explorer join timeout — yeni tracker; eski daemon thread terk edildi"
                    )
                    self._log_event(
                        "Warning: explorer thread timeout (mining treated as stopped)."
                    )
                    # Gecikmi _probe callback i eski oturuma yazmas n
                    self._explorer.on_update = None
                    self._explorer = ExplorerTracker(on_update=self._on_explorer_update)
                    # Fold + harici stop: motor_ops alt nda; join NCE motor kilidini b rak
                with self._motor_ops:
                    self._fold_active_motor_shares()
                    xmrig_err = self._stop_external(self._xmrig, "XMRig", timeout_s=6.0)
                    if xmrig_err is None:
                        self._xmrig = None
                    rigel_err = self._stop_external(self._rigel, "Rigel", timeout_s=6.0)
                    if rigel_err is None:
                        self._rigel = None
                    if self._stratum:
                        try:
                            self._stratum.stop()
                        except Exception:
                            pass
                        self._stratum = None
                thread = self._thread
                if thread is not None and thread.is_alive():
                    # Miner thread _halt/_start i in motor_ops ister burada tutulmaz
                    thread.join(timeout=10)
                with self._motor_ops:
                    # Join s ras nda yeniden a lm motor/stratum varsa tekrar kapat
                    if self._xmrig is not None:
                        e2 = self._stop_external(self._xmrig, "XMRig", timeout_s=4.0)
                        if e2 is None:
                            self._xmrig = None
                        elif xmrig_err is None:
                            xmrig_err = e2
                    if self._rigel is not None:
                        e2 = self._stop_external(self._rigel, "Rigel", timeout_s=4.0)
                        if e2 is None:
                            self._rigel = None
                        elif rigel_err is None:
                            rigel_err = e2
                    if self._stratum is not None:
                        try:
                            self._stratum.stop()
                        except Exception:
                            log.exception("stratum stop (after join)")
                        self._stratum = None
                        # Ref kayb / kme sonras yetim xmrig
                    try:
                        from engines.orphan_miners import kill_app_xmrig, list_app_xmrig

                        alive = list_app_xmrig()
                        if alive:
                            n, failed = kill_app_xmrig()
                            self._log_event(
                                f"Orphan XMRig cleanup: found={len(alive)} "
                                f"killed={n} remaining={failed or 'none'}"
                            )
                            if failed and xmrig_err is None:
                                xmrig_err = RuntimeError(
                                    f"orphan XMRig did not exit pid={failed}"
                                )
                    except Exception:
                        log.exception("orphan XMRig stop scan")
                    miner_alive = (
                        (self._xmrig is not None and self._xmrig.is_running())
                        or (self._rigel is not None and self._rigel.is_running())
                        or xmrig_err is not None
                        or rigel_err is not None
                    )
                thread_alive = thread is not None and thread.is_alive()
                if thread_alive or miner_alive:
                    self._stop_failed = True
                    self.stats.connected = False
                    parts = []
                    if thread_alive:
                        parts.append("miner thread still running")
                    if miner_alive:
                        parts.append(
                            f"external miner did not exit ({xmrig_err or rigel_err or 'process alive'})"
                        )
                    self.stats.status = (
                        "Stop failed: "
                        + "; ".join(parts)
                        + ". New session will not start."
                    )
                    self._log_event(self.stats.status)
                    self._emit()
                    return False

                self._thread = None
                self._stop_failed = False
                if self._gpu:
                    try:
                        self._gpu.close()
                    except Exception:
                        pass
                    self._gpu = None
                with self._motor_ops:
                    self._xmrig = None
                    self._rigel = None
                with self._job_lock:
                    self._invalidate_all_jobs("shutdown")
                    self._job = None
                err = self._block_store.drain(timeout_s=4.0)
                if err:
                    self.stats.block_store_error = err
                    self._log_event(err)
                self._block_store.stop()
                self.stats.connected = False
                self.stats.status = "Stopped."
                self._search_strategy_locked = False
                self._emit()
                return True
            finally:
                self._stopping = False

    def _strategy_kernel_args(self, work: WorkBatch) -> dict:
        from mining.search_strategy import SearchStrategy

        code = {
            SearchStrategy.SEQUENTIAL.value: 0,
            SearchStrategy.REVERSE.value: 1,
            SearchStrategy.RANDOMIZED.value: 2,
        }.get(str(work.strategy), 0)
        return {
            "strategy": code,
            "aff_a": int(work.affine_a) | (1 if code == 2 else 0),
            "aff_b": int(work.affine_b),
        }

    def _invalidate_all_jobs(self, reason: str) -> None:
        """clean=true / session: invalidate ALL known jobs and bump epoch."""
        self._work_epoch += 1
        for j in self._known_jobs:
            j.mark_invalidated()
        self._known_jobs.clear()
        self._log_event(
            f"All in-flight batches invalidated (epoch={self._work_epoch}): {reason}"
        )

    def _emit(self) -> None:
        self.stats.elapsed = max(0.0, time.time() - self._start_time) if self._start_time else 0.0
        self.stats.search_strategy = self.search_strategy()
        if self._block_store.last_error:
            self.stats.block_store_error = self._block_store.last_error
        if self.on_stats:
            overrides: dict[str, Any] = {}
            if self._best_broken_pending:
                self._best_broken_pending = False
                overrides["best_record_broken"] = True
                self.stats.best_record_broken = False
            if self._accepted_broken_pending:
                self._accepted_broken_pending = False
                overrides["accepted_record_broken"] = True
                self.stats.accepted_record_broken = False
            if overrides:
                self.on_stats(replace(self.stats, **overrides))
            else:
                self.on_stats(self.stats)

    def _best_hash_mode(self) -> str:
        mode = self._best_mode_cache
        if mode is None:
            env = (os.environ.get("EBF_BEST_HASH_MODE") or "").strip().lower()
            if env in ("gpu_batch", "accepted_only"):
                mode = env
            else:
                try:
                    mode = str(load_best_hash_state().get("mode") or "gpu_batch")
                except Exception:
                    mode = "gpu_batch"
                if mode not in ("gpu_batch", "accepted_only"):
                    mode = "gpu_batch"
            self._best_mode_cache = mode
        return mode

    def reload_best_hash_records(self) -> None:
        """Reload GPU/ACC best from disk into live stats (e.g. after Settings reset)."""
        self._load_best_into_stats(self.network_id or "btc")
        self._emit()

    def _load_best_into_stats(self, nid: str) -> None:
        st = self.stats
        st.network_difficulty = None
        st.best_difficulty = None
        st.best_hash_be_hex = None
        st.best_record_broken = False
        st.accepted_best_difficulty = None
        st.accepted_best_hash_be_hex = None
        st.accepted_record_broken = False
        st.last_accepted_difficulty = None
        self._best_record = None
        self._accepted_best_record = None
        if nid not in SUPPORTED_BEST_HASH_NETWORKS:
            return
        st.best_hash_mode = self._best_hash_mode()
        self._best_store_ok = True
        try:
            net = load_best_hash_state(strict=True)["records"].get(nid)
        except BestHashLoadError as exc:
            if exc.corrupt:
                bak = quarantine_corrupt_store()
                log.warning("best hash store corrupt (%s); quarantined to %s", exc, bak)
                self._best_store_ok = bak is not None
            else:
                log.warning("best hash store unreadable (%s); persistence disabled", exc)
                self._best_store_ok = False
            net = None
        except Exception as exc:
            log.warning("best hash load failed (%s); persistence disabled", exc)
            self._best_store_ok = False
            net = None
        if net is None:
            return
        self._best_record = net.gpu_best
        self._accepted_best_record = net.accepted_best
        if net.gpu_best:
            st.best_difficulty = net.gpu_best.difficulty
            st.best_hash_be_hex = net.gpu_best.hash_be_hex
        if net.accepted_best:
            st.accepted_best_difficulty = net.accepted_best.difficulty
            st.accepted_best_hash_be_hex = net.accepted_best.hash_be_hex

    def _track_best_hash(self, snap: Any, result: Any, verified_list: list[dict]) -> None:
        """Update GPU personal best from batch winner (gpu_batch mode only)."""
        nid = self.network_id
        if nid not in SUPPORTED_BEST_HASH_NETWORKS:
            return
        try:
            self.stats.network_difficulty = network_difficulty_from_nbits(snap.nbits)
        except (ValueError, TypeError):
            self.stats.network_difficulty = None
        mode = self._best_hash_mode()
        self.stats.best_hash_mode = mode
        if mode != "gpu_batch":
            return
        if not (result.best_hash_be_hex and result.best_nonce is not None):
            return
        cand = str(result.best_hash_be_hex).strip().lower()
        nonce_hex = f"{int(result.best_nonce):08x}"
        nonce_int = int(result.best_nonce)
        if not self._best_store_ok:
            return
        cached = self._best_record
        try:
            cached_int = hash_be_hex_to_int(cached.hash_be_hex) if cached else None
        except ValueError:
            cached_int = None
        try:
            cand_int = hash_be_hex_to_int(cand)
        except ValueError:
            return
        if not is_better_hash(cand_int, cached_int):
            return
        if not verify_best_candidate(snap.header_for_nonce(nonce_int), cand):
            log.warning("best hash candidate failed CPU verify; discarded (nonce=%s)", nonce_int)
            return
        had_previous = cached is not None
        try:
            rec = upsert_record_if_better(
                nid,
                hash_be_hex=cand,
                nonce_hex=nonce_hex,
                job_id=str(snap.job_id),
                nbits=str(snap.nbits),
                network_difficulty_at_time=self.stats.network_difficulty,
                kind="gpu",
            )
        except BestHashLoadError as exc:
            log.warning("best hash store unreadable; write skipped: %s", exc)
            self._best_store_ok = False
            return
        except Exception as exc:
            log.warning("best hash persist failed: %s", exc)
            return
        if rec:
            self._best_record = rec
            self.stats.best_difficulty = rec.difficulty
            self.stats.best_hash_be_hex = rec.hash_be_hex
            if had_previous:
                self.stats.best_record_broken = True
                self._best_broken_pending = True
            if self._work_ledger is not None:
                self._work_ledger.on_gpu_best(float(rec.difficulty), rec.hash_be_hex)

    def _track_last_accepted(self, entry: dict[str, Any]) -> None:
        """Session-only: difficulty of the most recent accepted share hash."""
        nid = self.network_id
        if nid not in SUPPORTED_BEST_HASH_NETWORKS:
            return
        hx = str(entry.get("hash") or "").strip().lower()
        if not hx:
            return
        try:
            self.stats.last_accepted_difficulty = difficulty_from_hash_int(
                hash_be_hex_to_int(hx)
            )
        except (TypeError, ValueError):
            return

    def _track_accepted_best(self, entry: dict[str, Any]) -> None:
        """Update accepted-share personal best after pool ACCEPTED (user shares only)."""
        nid = self.network_id
        if nid not in SUPPORTED_BEST_HASH_NETWORKS:
            return
        if not self._best_store_ok:
            return
        hx = str(entry.get("hash") or "").strip().lower()
        if not hx:
            return
        try:
            cand_int = hash_be_hex_to_int(hx)
        except ValueError:
            return
        cached = self._accepted_best_record
        try:
            cached_int = hash_be_hex_to_int(cached.hash_be_hex) if cached else None
        except ValueError:
            cached_int = None
        if not is_better_hash(cand_int, cached_int):
            return
        header_hex = str(entry.get("header80") or "")
        try:
            header = bytes.fromhex(header_hex) if header_hex else b""
        except ValueError:
            header = b""
        if header and not verify_best_candidate(header, hx):
            log.warning("accepted best failed CPU verify; discarded nonce=%s", entry.get("nonce_hex"))
            return
        had_previous = cached is not None
        try:
            rec = upsert_record_if_better(
                nid,
                hash_be_hex=hx,
                nonce_hex=str(entry.get("nonce_hex") or ""),
                job_id=str(entry.get("job_id") or ""),
                nbits=str(entry.get("nbits") or ""),
                network_difficulty_at_time=self.stats.network_difficulty,
                kind="accepted",
            )
        except BestHashLoadError as exc:
            log.warning("accepted best store unreadable; write skipped: %s", exc)
            self._best_store_ok = False
            return
        except Exception as exc:
            log.warning("accepted best persist failed: %s", exc)
            return
        if rec:
            self._accepted_best_record = rec
            self.stats.accepted_best_difficulty = rec.difficulty
            self.stats.accepted_best_hash_be_hex = rec.hash_be_hex
            if had_previous:
                self.stats.accepted_record_broken = True
                self._accepted_broken_pending = True
            if self._work_ledger is not None:
                self._work_ledger.on_accepted_best(float(rec.difficulty), rec.hash_be_hex)

    def _run(self, session: int) -> None:
        try:
            if not self._session_alive(session):
                self.stats.status = "Cancelled (before start)."
                self._emit()
                return
            self._preparing = True
            if self._profile.engine_kind == "managed_external" and self._profile.id == "xmr":
                self._run_xmrig(session)
                return
            if self._profile.engine_kind == "managed_external" and self._profile.id in (
                "rvn",
                "erg",
            ):
                self._run_rigel(self._profile.id, session)
                return

            from gpu.miner import GpuMiner, GpuUnavailableError
            from monitor.gpu_devices import resolve_gpu, temperature_for_bus

            prefer_bus = ""
            try:
                resolved = resolve_gpu(
                    bus_id=self.gpu_bus_id or None,
                    uuid=self.gpu_uuid or None,
                )
                prefer_bus = resolved.bus_id
                self._resolved_gpu_bus = resolved.bus_id
                self.stats.thermal_source = (
                    f"NVML bus={resolved.bus_id} uuid="
                    f"{(resolved.uuid[:13] + '…') if resolved.uuid else '—'}"
                )
                temp0, src0 = temperature_for_bus(resolved.bus_id)
                self.stats.gpu_temp = temp0
                self.stats.temp_readable = temp0 is not None
                if src0:
                    self.stats.thermal_source = src0
            except RuntimeError as exc:
                # NVML yok / oklu GPU se imsiz OpenCL yine denenebilir (tek kart)
                self._resolved_gpu_bus = ""
                self.stats.thermal_source = f"NVML missing/selection: {exc}"
                self._log_event(str(exc))
                if "Multiple GPUs" in str(exc):
                    self.stats.status = str(exc)
                    self._emit()
                    return

            try:
                self._gpu = GpuMiner(prefer_bus_id=prefer_bus or None)
                self.stats.device_name = self._gpu.device_name
            except GpuUnavailableError as exc:
                self.stats.status = f"GPU error: {exc}"
                self._emit()
                return

            if not self.stats.temp_readable and not self._resolved_gpu_bus:
                self.stats.temp_readable = self._temp.available
            if self._abort_if_temp_required():
                return
            if self.stats.temp_readable:
                self.stats.status = f"OpenCL ready: {self.stats.device_name}"
            # else: status already set by _abort_if_temp_required (override path)
            elif not (self.stats.status or "").startswith("WARNING"):
                self.stats.status = (
                    f"OpenCL ready: {self.stats.device_name}. "
                    "WARNING: mining without thermal guard."
                )
            self._emit()

            if not self._session_alive(session):
                self.stats.status = "Cancelled (after GPU prep)."
                self._emit()
                return
            self._preparing = False

            # Native: shared loop supports auto, game, or both (GPU ~50/50).
            if self.test_mode and not self._auto_enabled and self._game_enabled:
                self._run_game_test_mode()
            elif self.test_mode:
                self._run_test_mode()
            else:
                self._run_mainnet()
        except Exception as exc:
            log.exception("Miner error")
            self.stats.status = f"Error: {exc}"
            self._emit()
            with self._motor_ops:
                self._fold_active_motor_shares()
                if self._xmrig is not None:
                    if self._stop_external(self._xmrig, "XMRig", timeout_s=4.0) is None:
                        self._xmrig = None
                    else:
                        self._stop_failed = True
                if self._rigel is not None:
                    if self._stop_external(self._rigel, "Rigel", timeout_s=4.0) is None:
                        self._rigel = None
                    else:
                        self._stop_failed = True
                if self._stratum is not None:
                    try:
                        self._stratum.stop()
                    except Exception:
                        log.exception("stratum stop (_run except)")
                    self._stratum = None
                if self._gpu is not None:
                    try:
                        self._gpu.close()
                    except Exception:
                        pass
                    self._gpu = None
        finally:
            self._preparing = False

    def _run_xmrig(self, session: int = 0) -> None:
        from engines.fetch_miner import ensure_miner
        from engines.xmrig_runner import XmrigRunner
        from monitor.cpu_temp import CpuTemperatureMonitor
        from monitor.power import on_battery

        if self.test_mode:
            self.stats.status = "XMR test mode: no pool/XMRig (no local RandomX)."
            self.stats.connected = True
            self.stats.device_name = "XMRig (test — not submitted)"
            self._emit()
            while not self._stop.is_set():
                self._stop.wait(0.5)
                self._emit()
            return

        if self.pause_on_battery:
            batt = on_battery()
            if batt is True:
                self.stats.status = "Mining off on battery (pause_on_battery)."
                self._emit()
                return

        self.stats.status = "Downloading XMRig / verifying SHA-256…"
        self._emit()
        self._preparing = True
        try:
            exe = ensure_miner("xmrig", reverify=True)
        except Exception as exc:
            from engines.windows_security import (
                defender_exclusion_help,
                looks_like_defender_block,
            )

            if looks_like_defender_block(exc):
                self.stats.status = defender_exclusion_help("XMRig")
            else:
                self.stats.status = f"XMRig setup failed: {exc}"
            self._emit()
            return
        if not self._session_alive(session):
            self.stats.status = "Cancelled (after XMRig download)."
            self._emit()
            return
        self._preparing = False
        self.stats.coinbase_status = (
            "XMR: no automatic block explorer — accepted share ≠ block/payout. "
            f"If Windows Security blocks XMRig, add the {APP_NAME} folder to exclusions."
        )

        cpu_mon = CpuTemperatureMonitor()
        self.stats.thermal_source = cpu_mon.source_name
        self.stats.temp_readable = cpu_mon.available
        if self._abort_if_temp_required():
            return

        self.stats.device_name = f"XMRig {exe.parent.name}"
        if self.stats.temp_readable:
            self.stats.status = "Starting XMRig…"
        self._emit()

        shares = ManagedShareAccum()
        self._share_accum = shares
        motor_gen = 0
        self._motor_gen = 0
        self._donation_active = False
        self._mining_address = self.address

        def _push_share_stats(status: str = "") -> None:
            shares.set_donation_active(self._donation_active)
            self.stats.accepted = shares.display_accepted
            self.stats.app_donation_shares = shares.display_donation
            self.stats.engine_fee_shares = shares.display_fee
            self.stats.unattributed_shares = shares.display_unattr
            self.stats.rejected = shares.display_rejected
            self.stats.donation_active = self._donation_active
            if status:
                self.stats.status = status

        def _halt_xmrig() -> bool:
            nonlocal motor_gen
            with self._motor_ops:
                runner = self._xmrig
                # Ref UI stop ile silinmi olsa bile process_* bir kez fold
                self._retire_motor_into(shares, runner, motor_gen)
                _push_share_stats()
                if runner is None:
                    return True
                err = self._stop_external(runner, "XMRig", timeout_s=6.0)
                if err is None:
                    if self._xmrig is runner:
                        self._xmrig = None
                    return True
                self._stop_failed = True
                self.stats.status = f"XMRig stop failed: {err}"
                self._emit()
                return False

        def _on_snap(snap) -> None:
            if not self._session_alive(session):
                return
            gen = int(getattr(snap, "generation", 0) or motor_gen)
            if not shares.apply_snapshot(snap, gen):
                return
            self.stats.connected = snap.connected
            # Idle HTTP pause: do not let poller paint a stale non-zero hashrate.
            if getattr(self, "_xmrig_idle_paused", False):
                self.stats.hashrate = 0.0
            else:
                self.stats.hashrate = snap.hashrate
            job_label = str(getattr(snap, "job_id", "") or "")
            if job_label:
                self.stats.current_job_id = job_label
            snap_diff = getattr(snap, "difficulty", None)
            if snap_diff is not None:
                try:
                    self.stats.server_difficulty = float(snap_diff)
                except (TypeError, ValueError):
                    pass
            try:
                h_delta = int(getattr(snap, "hashes_delta", 0) or 0)
            except (TypeError, ValueError):
                h_delta = 0
            if h_delta > 0 and not getattr(self, "_xmrig_idle_paused", False):
                self.stats.total_hashes += h_delta
                try:
                    self.stats.lifetime_attempts = add_lifetime_attempts(
                        self.network_id, h_delta
                    )
                except OSError:
                    pass
            _push_share_stats(snap.status)
            if snap.donating:
                self.stats.coinbase_status = (
                    f"Engine fee share (not user accepted): +fee="
                    f"{self.stats.engine_fee_shares}"
                )
            self._emit()

        def _start_xmrig(addr: str) -> None:
            nonlocal motor_gen
            with self._motor_ops:
                if self._motor_start_blocked():
                    return
                motor_gen = shares.next_generation()
                self._motor_gen = motor_gen
                user = self._authorize_user(addr)
                host, port, password = self._pool_conn()
                try:
                    self._xmrig = XmrigRunner(
                        exe,
                        host=host,
                        port=port,
                        username=user,
                        password=password,
                        donate_level=self.xmrig_donate_level,
                        threads=self.cpu_thread_limit,
                        on_snapshot=_on_snap,
                        user_pool_hint="kryptex",
                        generation=motor_gen,
                        use_tls=bool(
                            self._pool_endpoint
                            and self._pool_endpoint.transport == "tls"
                        ),
                    )
                    self._xmrig.start()
                    self._xmrig_idle_paused = False
                except Exception as exc:
                    from engines.windows_security import (
                        defender_exclusion_help,
                        exe_quarantined_or_missing,
                        looks_like_defender_block,
                    )

                    self._xmrig = None
                    self._xmrig_idle_paused = False
                    if looks_like_defender_block(exc) or exe_quarantined_or_missing(exe):
                        self.stats.status = defender_exclusion_help("XMRig")
                    else:
                        self.stats.status = f"XMRig start failed: {exc}"
                    self._emit()
                    self._log_event(self.stats.status)
                    return
                self.stats.payout_address = addr
                self._log_event(
                    f"XMRig start user={user[:20]}… donate={self.xmrig_donate_level} "
                    f"threads={self.cpu_thread_limit or 'auto'} gen={motor_gen}"
                    + (" [donation]" if self._donation_active else "")
                )

        try:
            _start_xmrig(self.address)
            if is_effectively_enabled(self.app_donation, self.network_id):
                self._log_event(
                    f"{APP_NAME} donation on (XMR): worker reconnects each slice; "
                    "block in slice → full reward to donation address."
                )

            while not self._stop.is_set():
                if self.pause_on_battery and on_battery() is True:
                    self.stats.status = "On battery — stopping XMRig."
                    self._emit()
                    break
                temp = cpu_mon.read_celsius()
                self.stats.gpu_temp = temp  # UI field: XMR uses CPU °C here
                if cpu_mon.available:
                    self.stats.temp_readable = temp is not None
                    if temp is not None:
                        if temp >= self.pause_temp and not self._paused:
                            self._log_event(f"CPU thermal pause {temp}°C — XMRig stop")
                            if not _halt_xmrig():
                                break
                            self._paused = True
                            self.stats.paused_thermal = True
                            self.stats.status = (
                                f"CPU {temp}°C — XMRig paused "
                                f"(threshold {self.pause_temp}°C)."
                            )
                        elif temp <= self.resume_temp and self._paused:
                            want_addr = self._mining_address or self.address
                            # Pause s ras nda dilim kaym olabilir
                            want_don = self._desired_donation_active()
                            if want_don != self._donation_active:
                                self._donation_active = want_don
                                shares.set_donation_active(want_don)
                                want_addr = (
                                    donation_address_for(
                                        self.app_donation, self.network_id
                                    )
                                    if want_don
                                    else self.address
                                )
                                self._mining_address = want_addr
                                self.stats.donation_active = want_don
                            self._log_event(f"CPU thermal resume {temp}°C — XMRig restart")
                            _start_xmrig(want_addr)
                            if self._motor_start_blocked():
                                break
                            if self._xmrig is not None:
                                self._paused = False
                                self.stats.paused_thermal = False
                    elif self._paused:
                        self.stats.paused_thermal = True
                        self.stats.status = (
                            "CPU temperature unreadable — staying in thermal pause."
                        )
                    else:
                        self._log_event(
                            "CPU temperature unreadable — all mining paused"
                        )
                        if not _halt_xmrig():
                            break
                        self._paused = True
                        self.stats.paused_thermal = True
                        self.stats.status = (
                            "CPU temperature unreadable — all mining paused."
                        )
                else:
                    self.stats.temp_readable = False
                    if not self._paused:
                        self._log_event(
                            "CPU sensor unavailable — all mining paused"
                        )
                        if not _halt_xmrig():
                            break
                        self._paused = True
                        self.stats.paused_thermal = True
                        self.stats.status = (
                            "CPU temperature unreadable — all mining paused."
                        )

                if self._paused:
                    # Motor kapal yken ba dilimini adreste tut (resume do ru adres)
                    self.stats.paused_idle = False
                    want = self._desired_donation_active()
                    if want != self._donation_active:
                        self._donation_active = want
                        shares.set_donation_active(want)
                        self._mining_address = (
                            donation_address_for(self.app_donation, self.network_id)
                            if want
                            else self.address
                        )
                        self.stats.donation_active = want
                    self._emit()
                    self._stop.wait(1.0)
                    continue

                # XMRig: binary only (no live thread %). ACTIVE→pause, IDLE→resume
                # at configured cpu_thread_limit. HTTP failure does not flip state.
                idle_state = self._eval_idle_policy()
                if idle_state.mode == "off":
                    want_pause = False
                elif idle_state.mode == "active":
                    want_pause = True
                else:
                    want_pause = False
                if want_pause != getattr(self, "_xmrig_idle_paused", False):
                    xm = self._xmrig
                    if xm is not None and xm.is_running():
                        if want_pause:
                            if xm.pause_mining():
                                self._xmrig_idle_paused = True
                                self.stats.paused_idle = True
                                self.stats.hashrate = 0.0
                                self._set_activity_ui("Using PC · Mining paused")
                                self._log_event("XMRig HTTP pause (using PC)")
                            else:
                                self._set_activity_ui(
                                    "Using PC · Pause failed (still mining)"
                                )
                                self._log_event("XMRig HTTP pause failed")
                        else:
                            if xm.resume_mining():
                                self._xmrig_idle_paused = False
                                self.stats.paused_idle = False
                                self._set_activity_ui("AFK · Mining resumed")
                                self._log_event(
                                    "XMRig HTTP resume (configured thread limit)"
                                )
                            else:
                                self._set_activity_ui(
                                    "AFK · Resume failed (still paused)"
                                )
                                self._log_event("XMRig HTTP resume failed")
                    self.stats.paused_idle = bool(
                        getattr(self, "_xmrig_idle_paused", False)
                    )
                    if self.stats.paused_idle:
                        self.stats.hashrate = 0.0
                elif idle_state.mode == "off":
                    self._set_activity_ui("")
                elif self._xmrig_idle_paused:
                    self._set_activity_ui("Using PC · Mining paused")
                else:
                    self._set_activity_ui("AFK · Mining resumed")

                want = self._desired_donation_active()
                if want != self._donation_active:
                    if not _halt_xmrig():
                        break
                    new_addr = (
                        donation_address_for(self.app_donation, self.network_id)
                        if want
                        else self.address
                    )
                    self._log_event(
                        "XMR donation slice OPEN."
                        if want
                        else "XMR donation slice closed."
                    )
                    _start_xmrig(new_addr)
                    if self._motor_start_blocked():
                        break
                    if self._xmrig is None:
                        self._emit()
                        self._stop.wait(1.0)
                        continue
                    self._donation_active = want
                    shares.set_donation_active(want)
                    self._mining_address = new_addr
                    self.stats.donation_active = want

                if self._xmrig is None or not self._xmrig.is_running():
                    from engines.windows_security import (
                        defender_exclusion_help,
                        exe_quarantined_or_missing,
                    )

                    self._log_event("XMRig process gone/ended — will retry")
                    if exe_quarantined_or_missing(exe):
                        _halt_xmrig()
                        self.stats.status = defender_exclusion_help("XMRig")
                        self.stats.connected = False
                        self._emit()
                        break
                    _halt_xmrig()
                    if self._motor_start_blocked():
                        break
                    self.stats.status = "XMRig process ended — restarting…"
                    self.stats.connected = False
                    self._emit()
                    self._stop.wait(2.0)
                    if self._stop.is_set():
                        break
                    _start_xmrig(self._mining_address or self.address)
                    continue
                self._emit()
                self._stop.wait(1.0)
        finally:
            _halt_xmrig()

    def _run_rigel(self, network_id: str, session: int = 0) -> None:
        from engines.dag_gate import check_autolykos_vram, check_kawpow_vram
        from engines.fetch_miner import ensure_miner
        from engines.rigel_runner import (
            RigelRunner,
            probe_rigel_devices,
            resolve_rigel_device_index,
        )
        from monitor.gpu_devices import (
            resolve_gpu,
            temperature_for_bus,
        )

        if network_id == "rvn":
            algo, coin, api_port, label = "kawpow", "rvn", 5001, "KawPoW"
            gate_fn = check_kawpow_vram
        elif network_id == "erg":
            algo, coin, api_port, label = "autolykos2", "erg", 5002, "Autolykos2"
            gate_fn = check_autolykos_vram
        else:
            raise ValueError(f"Rigel network not supported: {network_id}")

        if self.test_mode:
            self.stats.status = f"{network_id.upper()} test mode: no Rigel/pool."
            self.stats.connected = True
            self.stats.device_name = "Rigel (test)"
            self._emit()
            while not self._stop.is_set():
                self._stop.wait(0.5)
                self._emit()
            return

            # Memory gate before downloading miner when possible
        try:
            gpu = resolve_gpu(
                bus_id=self.gpu_bus_id or None,
                uuid=self.gpu_uuid or None,
                nvidia_only=True,
            )
        except RuntimeError as exc:
            self.stats.status = (
                f"{network_id.upper()}: NVIDIA CUDA GPU required (Rigel). {exc}"
            )
            self._emit()
            return
        try:
            gate = gate_fn(
                free_vram_bytes=gpu.free_vram_bytes,
                total_vram_bytes=gpu.total_vram_bytes,
            )
        except RuntimeError as exc:
            self.stats.status = (
                f"Height/VRAM could not be verified (estimate not exact): {exc}"
            )
            self._emit()
            return
        self._log_event(f"VRAM gate ({label}): {gate.message}")
        if not gate.ok:
            self.stats.status = gate.message
            self._emit()
            return

        self.stats.status = "Downloading Rigel / verifying SHA-256…"
        self._emit()
        self._preparing = True
        exe = ensure_miner("rigel", reverify=True)
        if not self._session_alive(session):
            self.stats.status = "Cancelled (after Rigel download)."
            self._emit()
            return

            # Ger ek Rigel cihaz listesi ile PCI/UUID do rula (NVML s ras varsay lmaz)
        try:
            listed = probe_rigel_devices(exe)
            rigel_d = resolve_rigel_device_index(
                selected_bus=gpu.bus_id,
                selected_uuid=gpu.uuid or "",
                rigel_devices=listed,
            )
        except RuntimeError as exc:
            self._preparing = False
            self.stats.status = str(exc)
            self._emit()
            return
        if not self._session_alive(session):
            self.stats.status = "Cancelled (after Rigel device validation)."
            self._emit()
            return
        self._preparing = False

        self.stats.device_name = f"{gpu.name} bus={gpu.bus_id} rigel_d={rigel_d}"
        self.stats.thermal_source = (
            f"NVML bus={gpu.bus_id} (Rigel -d={rigel_d} --list-devices; "
            f"NVML index={gpu.index} not used)"
        )
        temp0, src0 = temperature_for_bus(gpu.bus_id)
        self.stats.gpu_temp = temp0
        self.stats.temp_readable = temp0 is not None
        if src0:
            self.stats.thermal_source = src0
        if self._abort_if_temp_required():
            return
        self.stats.coinbase_status = (
            f"{network_id.upper()}: accepted share ≠ block/payout; "
            "automatic block verification off without pool account API "
            "(unsupported feature — not finished)."
        )
        self._resolved_gpu_bus = gpu.bus_id

        shares = ManagedShareAccum()
        self._share_accum = shares
        motor_gen = 0
        self._motor_gen = 0
        self._donation_active = False
        self._mining_address = self.address

        def _push_share_stats(status: str = "") -> None:
            shares.set_donation_active(self._donation_active)
            self.stats.accepted = shares.display_accepted
            self.stats.app_donation_shares = shares.display_donation
            self.stats.engine_fee_shares = shares.display_fee
            self.stats.unattributed_shares = shares.display_unattr
            self.stats.rejected = shares.display_rejected
            self.stats.donation_active = self._donation_active
            if status:
                self.stats.status = status

        def _halt_rigel() -> bool:
            nonlocal motor_gen
            with self._motor_ops:
                runner = self._rigel
                self._retire_motor_into(shares, runner, motor_gen)
                _push_share_stats()
                if runner is None:
                    return True
                err = self._stop_external(runner, "Rigel", timeout_s=6.0)
                if err is None:
                    if self._rigel is runner:
                        self._rigel = None
                    return True
                self._stop_failed = True
                self.stats.status = f"Rigel stop failed: {err}"
                self._emit()
                return False

        def _on_snap(snap) -> None:
            if not self._session_alive(session):
                return
            gen = int(getattr(snap, "generation", 0) or motor_gen)
            if not shares.apply_snapshot(snap, gen):
                return
            self.stats.connected = snap.connected
            self.stats.hashrate = snap.hashrate
            _push_share_stats(snap.status)
            if snap.fee_period:
                self.stats.coinbase_status = (
                    f"Rigel fee share (not user accepted): "
                    f"{self.stats.engine_fee_shares}"
                )
            self._emit()

        def _start_rigel(addr: str) -> None:
            nonlocal motor_gen
            with self._motor_ops:
                if self._motor_start_blocked():
                    return
                motor_gen = shares.next_generation()
                self._motor_gen = motor_gen
                user = self._authorize_user(addr)
                host, port, password = self._pool_conn()
                self._rigel = RigelRunner(
                    exe,
                    algorithm=algo,
                    coin=coin,
                    host=host,
                    port=port,
                    username=user,
                    password=password,
                    device_index=rigel_d,
                    api_port=api_port,
                    on_snapshot=_on_snap,
                    user_pool_hint="2miners",
                    env_extra={"CUDA_DEVICE_ORDER": "PCI_BUS_ID"},
                    generation=motor_gen,
                    use_tls=bool(
                        self._pool_endpoint
                        and self._pool_endpoint.transport == "tls"
                    ),
                )
                self._rigel.start()
                self._rigel_idle_paused = False
                self.stats.payout_address = addr
                self._log_event(
                    f"Rigel {network_id.upper()} start bus={gpu.bus_id} "
                    f"rigel_d={rigel_d} (NVML idx={gpu.index}) user={user[:16]}… "
                    f"N/epoch={gate.epoch} gen={motor_gen}"
                    + (" [donation]" if self._donation_active else "")
                )

        self.stats.status = f"Starting Rigel {label}…"
        self._emit()
        try:
            _start_rigel(self.address)
            if is_effectively_enabled(self.app_donation, self.network_id):
                self._log_event(
                    f"{APP_NAME} donation on ({network_id.upper()}): worker reconnects each slice; "
                    "block in slice → full reward to donation."
                )

            while not self._stop.is_set():
                temp, src = temperature_for_bus(gpu.bus_id)
                self.stats.thermal_source = src
                self.stats.gpu_temp = temp
                self.stats.temp_readable = temp is not None
                if temp is not None:
                    if temp >= self.pause_temp and not self._paused:
                        self._log_event(
                            f"GPU thermal pause {temp}°C bus={gpu.bus_id} — Rigel stop"
                        )
                        if not _halt_rigel():
                            break
                        self._paused = True
                        self.stats.paused_thermal = True
                        self.stats.status = (
                            f"Temperature {temp}°C — Rigel paused "
                            f"(threshold {self.pause_temp}°C)."
                        )
                    elif temp <= self.resume_temp and self._paused:
                        want_addr = self._mining_address or self.address
                        want_don = self._desired_donation_active()
                        if want_don != self._donation_active:
                            self._donation_active = want_don
                            shares.set_donation_active(want_don)
                            want_addr = (
                                donation_address_for(
                                    self.app_donation, self.network_id
                                )
                                if want_don
                                else self.address
                            )
                            self._mining_address = want_addr
                            self.stats.donation_active = want_don
                        self._log_event(f"GPU thermal resume {temp}°C — Rigel restart")
                        _start_rigel(want_addr)
                        if self._motor_start_blocked():
                            break
                        if self._rigel is not None:
                            self._paused = False
                            self.stats.paused_thermal = False
                elif self._paused:
                    self.stats.paused_thermal = True
                    self.stats.status = (
                        "GPU temperature unreadable — staying in thermal pause."
                    )
                else:
                    self._log_event(
                        "GPU temperature unreadable — all mining paused"
                    )
                    if not _halt_rigel():
                        break
                    self._paused = True
                    self.stats.paused_thermal = True
                    self.stats.status = (
                        "GPU temperature unreadable — all mining paused."
                    )

                if self._paused:
                    self.stats.paused_idle = False
                    want = self._desired_donation_active()
                    if want != self._donation_active:
                        self._donation_active = want
                        shares.set_donation_active(want)
                        self._mining_address = (
                            donation_address_for(self.app_donation, self.network_id)
                            if want
                            else self.address
                        )
                        self.stats.donation_active = want
                    self._emit()
                    self._stop.wait(1.0)
                    continue

                # Rigel: binary auto-idle only (no live %). ACTIVE/0% → halt once;
                # IDLE/>0% → start once. No duty-cycle. Pool reconnect + possible DAG rebuild.
                idle_state = self._eval_idle_policy()
                want_idle_pause = idle_state.scale <= 0.0 or idle_state.mode == "active"
                # When feature off, scale=1 and mode=off → do not pause.
                if idle_state.mode == "off":
                    want_idle_pause = False
                elif idle_state.mode == "idle":
                    want_idle_pause = idle_state.scale <= 0.0
                else:
                    # active mode: pause hashing (binary) — fine % not supported on Rigel
                    want_idle_pause = True

                if want_idle_pause and not self._rigel_idle_paused:
                    self._log_event(
                        "Rigel auto-idle ACTIVE — pausing miner "
                        "(pool will reconnect on resume; DAG may rebuild)."
                    )
                    if not _halt_rigel():
                        break
                    self._rigel_idle_paused = True
                    self.stats.paused_idle = True
                    self._set_activity_ui("Using PC · Mining paused")
                    self.stats.coinbase_status = (
                        "Using PC (Rigel): mining paused. Resume when AFK may "
                        "reconnect the pool and rebuild DAG."
                    )
                    self.stats.status = self.stats.coinbase_status
                elif (not want_idle_pause) and self._rigel_idle_paused:
                    self._log_event(
                        "Rigel AFK — resuming at configured capacity "
                        "(pool reconnect / DAG rebuild possible)."
                    )
                    _start_rigel(self._mining_address or self.address)
                    if self._motor_start_blocked():
                        break
                    if self._rigel is not None:
                        self._rigel_idle_paused = False
                        self.stats.paused_idle = False
                        self._set_activity_ui("AFK · Mining resumed")
                        self.stats.coinbase_status = ""
                self.stats.paused_idle = bool(self._rigel_idle_paused)
                if idle_state.mode == "off":
                    self._set_activity_ui("")
                if self._rigel_idle_paused:
                    self._emit()
                    self._stop.wait(1.0)
                    continue

                want = self._desired_donation_active()
                if want != self._donation_active:
                    if not _halt_rigel():
                        break
                    new_addr = (
                        donation_address_for(self.app_donation, self.network_id)
                        if want
                        else self.address
                    )
                    self._log_event(
                        f"Rigel donation slice OPEN ({network_id})."
                        if want
                        else f"Rigel donation slice closed ({network_id})."
                    )
                    _start_rigel(new_addr)
                    if self._motor_start_blocked():
                        break
                    if self._rigel is None:
                        self._emit()
                        self._stop.wait(1.0)
                        continue
                    self._donation_active = want
                    shares.set_donation_active(want)
                    self._mining_address = new_addr
                    self.stats.donation_active = want

                if self._rigel is None or not self._rigel.is_running():
                    self._log_event("Rigel process gone/ended — will retry")
                    _halt_rigel()
                    if self._motor_start_blocked():
                        break
                    self.stats.status = "Rigel process ended — restarting…"
                    self.stats.connected = False
                    self._emit()
                    self._stop.wait(2.0)
                    if self._stop.is_set():
                        break
                    _start_rigel(self._mining_address or self.address)
                    continue
                self._emit()
                self._stop.wait(1.0)
        finally:
            _halt_rigel()

    def is_game_mode(self) -> bool:
        return bool(self._game_enabled)

    def is_auto_mode(self) -> bool:
        return bool(self._auto_enabled)

    def is_game_board_open(self) -> bool:
        return bool(self._game_board_open)

    def set_game_board_open(self, open_: bool) -> None:
        """
        Scratch window visibility. Open → Game shares Intensity (~50/50 with Auto).
        Closed → Game releases GPU; Intensity is fully Automatic.
        """
        want = bool(open_)
        if self._game_board_open == want:
            return
        self._game_board_open = want
        self._refresh_session_kind()
        if want:
            self._game_wake.set()
            if self._auto_enabled and self._game_enabled:
                self.stats.status = (
                    "Auto + Game Mode · GPU split ~50/50 — board open."
                )
        elif self._auto_enabled and self._game_enabled:
            self.stats.status = (
                "Game board closed — Intensity 100% Automatic. "
                "Reopen Game Mode to resume the 50/50 split."
            )
        self._emit()

    def _game_gpu_active(self) -> bool:
        """Game may consume GPU only while the board UI is open."""
        return bool(self._game_enabled and self._game_board_open)

    def _refresh_session_kind(self) -> None:
        if self._auto_enabled and self._game_enabled:
            self._session_kind = "both"
        elif self._game_enabled:
            self._session_kind = "game"
        else:
            self._session_kind = "auto"
        self.stats.session_kind = self._session_kind
        # Surface dual mode in status when both are on and board is open.
        if self._auto_enabled and self._game_gpu_active():
            if "GPU split" not in (self.stats.status or ""):
                self.stats.status = (
                    "Auto + Game Mode · GPU split ~50/50 — hashing both workloads."
                )

    def enqueue_game_tile(self, tile_id: int) -> tuple[bool, str]:
        """UI thread: queue a tile on the live EN2 board."""
        return self.enqueue_game_at(None, int(tile_id))

    def enqueue_game_at(
        self, extranonce2: int | None, tile_id: int
    ) -> tuple[bool, str]:
        """
        Queue a tile; optionally retarget live job EN2 first (mega-map click).
        Hashing starts only from the game/mine loop.
        """
        if not self.is_game_mode():
            return False, "game mode not active"
        tid = int(tile_id)
        from game.tile_space import TILE_COUNT

        if tid < 0 or tid >= TILE_COUNT:
            return False, "tile out of range"
        if extranonce2 is not None:
            ok_sync, sync_msg = self._retarget_game_en2(int(extranonce2))
            if not ok_sync:
                return False, sync_msg
        if self._scratch is None:
            self._ensure_game_board(force_new=True, reason="enqueue")
        if self._scratch is None:
            return False, "no board"
        if not self._game_board_mineable(self._scratch):
            return False, "board not mineable — wait for live job"
        ok, msg = self._scratch.enqueue(tid)
        if ok:
            self._game_wake.set()
            self._publish_game_metrics()
            self._emit()
        return ok, msg

    def _retarget_game_en2(self, en2: int) -> tuple[bool, str]:
        """Point live job + active scratch at the given extranonce2."""
        from audit.work_family import family_from_job
        from mining.bitcoin import extranonce2_bytes

        with self._job_lock:
            job = self._job
            if job is None or not job.accept_new_work():
                return False, "no live job"
            limit = 1 << (8 * int(job.extranonce2_size or 4))
            en2 = int(en2) % limit
            want_hex = extranonce2_bytes(en2, job.extranonce2_size).hex()
            if int(job.extranonce2) == en2 and job.extranonce2_hex() == want_hex:
                # Already on this EN2 — reuse matching board if present.
                pass
            else:
                if self._scratch is not None:
                    self._scratch.interrupt_active("map navigate")
                job.extranonce2 = en2
                try:
                    job.rebuild_work()
                    job.configure_search_strategy(
                        job.search_strategy,
                        work_family_id=family_from_job(job),
                    )
                except Exception as exc:
                    return False, f"EN2 retarget failed: {exc}"

        # Prefer an existing board for this EN2 on the same job.
        with self._game_boards_lock:
            for i, s in enumerate(self._game_boards):
                try:
                    if int(str(s.board.extranonce2_hex), 16) != en2:
                        continue
                except ValueError:
                    continue
                if str(s.board.job_id) != str(
                    getattr(self._job, "job_id", "")
                ):
                    continue
                self._game_board_index = i
                self._scratch = s
                # Soft reload: UI merges tiles without snapping the camera.
                self._game_board_reload_pending = True
                self._publish_game_metrics()
                return True, "switched"
        ok = self._ensure_game_board(
            force_new=True,
            reason=f"map EN2 {en2}",
            keep_prior_boards=True,
        )
        if not ok:
            return False, "could not open board for EN2"
        return True, "opened"

    def game_scratch(self):
        return self._scratch

    def game_new_board(self) -> tuple[bool, str]:
        """Manual: bump extranonce2 and open a fresh 2³² board (keep prior boards)."""
        if not self.is_game_mode() or not self.is_running():
            return False, "game mode not active"
        with self._game_boards_lock:
            if self._scratch is not None:
                self._scratch.interrupt_active("manual new board")
            ok = self._bump_game_board_extranonce(manual=True)
        if not ok:
            return False, "no live job — wait for pool work"
        self._game_wake.set()
        self._emit()
        return True, "new board"

    def game_prev_board(self) -> tuple[bool, str]:
        return self._game_goto_board(self._game_board_index - 1)

    def game_next_board(self) -> tuple[bool, str]:
        return self._game_goto_board(self._game_board_index + 1)

    def game_goto_board(self, index: int) -> tuple[bool, str]:
        return self._game_goto_board(int(index))

    def game_tile_snapshot(self) -> list[dict]:
        """Non-UNOPENED tiles of the active board (for UI reload after switch)."""
        scratch = self._scratch
        if scratch is None:
            return []
        out: list[dict] = []
        for t in scratch.snapshot_tiles():
            if t.state.value == "UNOPENED":
                continue
            out.append(
                {
                    "tile_id": t.tile_id,
                    "state": t.state.value,
                    "best_difficulty": t.best_difficulty,
                    "best_hash_be_hex": t.best_hash_be_hex,
                    "hashes": t.hashes,
                    "share_candidates": t.share_candidates,
                    "accepted": t.accepted,
                    "rejected": t.rejected,
                    "processing_time_s": t.processing_time_s,
                    "start_nonce": t.start_nonce,
                    "end_nonce": t.end_nonce,
                    "next_nonce": t.next_nonce,
                    "board_id": scratch.board.board_id,
                    "extranonce2": scratch.board.extranonce2_hex,
                }
            )
        return out

    def _game_board_mineable(self, scratch) -> bool:
        if scratch is None:
            return False
        with self._job_lock:
            job = self._job
            if job is None or not job.accept_new_work():
                return False
            session = int(self._stratum.session_id) if self._stratum else 0
            try:
                # Compare identity fields without requiring live en2 match yet.
                if str(job.job_id) != str(scratch.board.job_id):
                    return False
                if str(job.prevhash) != str(scratch.board.prevhash):
                    return False
                if int(session) != int(scratch.board.session_id) and not self.test_mode:
                    # Session change invalidates submits; still allow view.
                    return False
            except Exception:
                return False
        return True

    def _game_goto_board(self, index: int) -> tuple[bool, str]:
        if not self.is_game_mode():
            return False, "game mode not active"
        with self._game_boards_lock:
            if not self._game_boards:
                return False, "no boards"
            if index < 0 or index >= len(self._game_boards):
                return False, "board out of range"
            if self._scratch is not None:
                self._scratch.interrupt_active("board switch")
            scratch = self._game_boards[index]
            self._game_board_index = index
            self._scratch = scratch
            # Sync live job extranonce2 to this board so mining/submit match header.
            synced = self._sync_job_to_board(scratch)
            self._game_board_reload_pending = True
            self._publish_game_metrics()
            self._set_game_event(
                "board_switch",
                f"Board {index + 1}/{len(self._game_boards)} · EN2 {scratch.board.extranonce2_hex}"
                + ("" if synced else " (view only — job mismatch)"),
            )
        self._game_wake.set()
        self._emit()
        return True, "switched"

    def _sync_job_to_board(self, scratch) -> bool:
        """Point MiningJob midstate/en2 at the selected board (same job family only)."""
        from audit.work_family import family_from_job

        with self._job_lock:
            job = self._job
            if job is None or not job.accept_new_work():
                return False
            if str(job.job_id) != str(scratch.board.job_id):
                return False
            if str(job.prevhash) != str(scratch.board.prevhash):
                return False
            try:
                en2 = int(str(scratch.board.extranonce2_hex), 16)
            except ValueError:
                return False
            job.extranonce2 = en2
            try:
                job.rebuild_work()
                job.configure_search_strategy(
                    job.search_strategy,
                    work_family_id=family_from_job(job),
                )
            except Exception:
                # Test-mode jobs may lack coinbase — keep header if already set.
                if len(job._header_prefix) != 76:
                    return False
            # Refresh board header_prefix if rebuild changed it (should match).
            if bytes(job._header_prefix) != bytes(scratch.board.header_prefix):
                # Board was built from older midstate; reject mining mismatch.
                return False
        return True

    def _publish_game_metrics(self, *, tile_update: Optional[dict] = None) -> None:
        scratch = self._scratch
        if scratch is None:
            self.stats.game_board_id = ""
            self.stats.game_tiles_revealed = 0
            self.stats.game_metrics = {}
            self.stats.game_board_index = 0
            self.stats.game_board_count = 0
            return
        m = scratch.metrics()
        m["board_index"] = int(self._game_board_index)
        m["board_count"] = len(self._game_boards)
        m["board_label"] = (
            f"{self._game_board_index + 1}/{max(1, len(self._game_boards))}"
        )
        m["mineable"] = bool(self._game_board_mineable(scratch))
        m["dual_mode"] = bool(self._auto_enabled and self._game_gpu_active())
        m["board_open"] = bool(self._game_board_open)
        with self._job_lock:
            en2_size = int(
                getattr(self._job, "extranonce2_size", None)
                or getattr(self._stratum, "extranonce2_size", None)
                or 4
            )
        m["extranonce2_size"] = en2_size
        try:
            m["live_en2_int"] = int(str(scratch.board.extranonce2_hex), 16)
        except ValueError:
            m["live_en2_int"] = 0
        with self._game_boards_lock:
            boards_sum = sum(int(s.tiles_revealed()) for s in self._game_boards)
        # Prefer monotonic session counter; fall back to in-memory board sum.
        m["tiles_revealed_session"] = max(
            int(self._game_tiles_completed_session), boards_sum
        )
        m["tiles_revealed_board"] = int(m.get("tiles_revealed") or 0)
        m["active_tile"] = self._game_active_tile_id
        total_gpu = max(1e-9, float(self._auto_gpu_s) + float(self._game_gpu_s))
        if self._auto_enabled and self._game_gpu_active():
            m["auto_gpu_share_pct"] = 100.0 * float(self._auto_gpu_s) / total_gpu
            m["game_gpu_share_pct"] = 100.0 * float(self._game_gpu_s) / total_gpu
        elif self._game_gpu_active():
            m["auto_gpu_share_pct"] = 0.0
            m["game_gpu_share_pct"] = 100.0
        else:
            m["auto_gpu_share_pct"] = 100.0 if self._auto_enabled else 0.0
            m["game_gpu_share_pct"] = 0.0
        self.stats.game_board_id = str(m.get("board_id") or "")
        self.stats.game_tiles_revealed = int(m.get("tiles_revealed_session") or 0)
        self.stats.game_metrics = m
        self.stats.game_board_index = int(self._game_board_index)
        self.stats.game_board_count = len(self._game_boards)
        if self._game_board_reload_pending:
            self.stats.game_board_reload = True
            self._game_board_reload_pending = False
        else:
            self.stats.game_board_reload = False
        if tile_update is not None:
            self.stats.game_tile_update = dict(tile_update)

    def _set_game_event(self, event: str, detail: str = "") -> None:
        self.stats.game_event = event
        self.stats.game_event_detail = detail
        self._log_event(f"Game: {event} — {detail}" if detail else f"Game: {event}")

    def _attach_session_kind(self, kind: str) -> None:
        """Enable Auto or Game on an already-running native BTC session."""
        kind = (kind or "auto").strip().lower()
        if self.network_id != "btc" or self._profile.engine_kind != "native_sha256d":
            raise ValueError("Combined Auto+Game requires BTC native OpenCL.")
        if kind == "game":
            if self._game_enabled:
                raise RuntimeError("Game Mode already active.")
            self._game_enabled = True
            self._game_gpu_s = float(self._auto_gpu_s)  # start balanced
            if self._scratch is None and self._job is not None:
                self._ensure_game_board(force_new=True, reason="attach game")
            self._refresh_session_kind()
            self._set_game_event(
                "board_ready",
                "Game Mode attached — GPU split ~50/50 with automatic mining.",
            )
            self._game_wake.set()
            self._emit()
            return
        if kind == "auto":
            if self._auto_enabled:
                raise RuntimeError("Automatic mining already active.")
            self._auto_enabled = True
            self._auto_gpu_s = float(self._game_gpu_s)
            self._refresh_session_kind()
            self.stats.status = (
                "Automatic mining attached — GPU split ~50/50 with Game Mode."
            )
            self._emit()
            return
        raise ValueError(f"Unknown session_kind: {kind}")

    def _run_game_test_mode(self) -> None:
        """Local Game Mode without Stratum (TEST MODE) — still real SHA256d on GPU."""
        from mining.bitcoin import midstate_from_header
        from mining.job import MiningJob

        self.stats.test_mode = True
        self.stats.connected = True
        self.stats.difficulty = 0.0001
        self.stats.status = (
            "Game Mode TEST — local SHA256d; shares are not sent to a pool."
        )
        genesis = bytes.fromhex(
            "0100000000000000000000000000000000000000000000000000000000000000"
            "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
            "4b1e5e4a29ab5f49ffff001d1dac2b7c"
        )
        job = MiningJob(
            job_id="game-test",
            prevhash="0" * 64,
            coinb1="",
            coinb2="",
            merkle_branches=[],
            version="01000000",
            nbits="1d00ffff",
            ntime="29ab5f49",
            clean_jobs=True,
            extranonce1="",
            extranonce2_size=4,
            difficulty=0.0001,
            diff_at_notify=0.0001,
            generation=1,
        )
        job._merkle_root = bytes(32)
        job._header_prefix = genesis[:76]
        job._midstate = midstate_from_header(genesis)
        job._midstate_key = genesis[:64]
        job._tail = genesis[64:76]
        with self._job_lock:
            self._known_jobs = [job]
            self._job = job
            self._work_epoch = 1
        self._game_prevhash = job.prevhash
        self._auto_enabled = False
        self._game_enabled = True
        self._game_board_open = True
        self._refresh_session_kind()
        self._ensure_game_board(force_new=True, reason="test board")
        self._mine_loop()

    def _ensure_game_board(
        self,
        *,
        force_new: bool = False,
        reason: str = "",
        reset_history: bool = False,
        keep_prior_boards: bool = True,
    ) -> bool:
        with self._job_lock:
            job = self._job
            if job is None or not job.accept_new_work():
                return False
            session = int(self._stratum.session_id) if self._stratum else 0
            snap = job.snapshot(
                validity_epoch=self._work_epoch, session_id=session
            )
        with self._game_boards_lock:
            scratch = self._scratch
            if (
                not force_new
                and scratch is not None
                and scratch.board.matches_snapshot(
                    session_id=snap.session_id,
                    job_id=snap.job_id,
                    header_prefix=snap.header_prefix,
                    extranonce2_hex=snap.extranonce2_hex,
                )
            ):
                return True
            from game.scratch_session import ScratchSession

            if reset_history:
                for old in self._game_boards:
                    old.interrupt_active(reason or "job changed")
                    old.invalidate_board(reason or "job changed")
                self._game_boards = []
                self._game_board_index = -1
                self._game_tiles_completed_session = 0
            elif scratch is not None and not keep_prior_boards:
                scratch.interrupt_active(reason or "new board")
                scratch.invalidate_board(reason or "new board")
            elif scratch is not None:
                scratch.interrupt_active(reason or "new board")

            new_s = ScratchSession.new_board(
                session_id=snap.session_id,
                job_id=snap.job_id,
                header_prefix=snap.header_prefix,
                extranonce2_hex=snap.extranonce2_hex,
                prevhash=snap.prevhash,
                ntime=snap.ntime,
                nbits=snap.nbits,
                generation=snap.generation,
            )
            self._game_boards.append(new_s)
            # Cap history (memory): drop oldest view-only boards beyond 32.
            if len(self._game_boards) > 32:
                drop = len(self._game_boards) - 32
                self._game_boards = self._game_boards[drop:]
            self._game_board_index = len(self._game_boards) - 1
            self._scratch = new_s
            self._game_board_gen += 1
            self._game_board_reload_pending = True
            self._publish_game_metrics()
            self._set_game_event("board_ready", reason or f"job={snap.job_id}")
            return True

    def _game_on_new_job(self, job, clean: bool) -> None:
        prev = self._game_prevhash
        new_prev = str(job.prevhash or "")
        self._game_prevhash = new_prev
        if prev is not None and prev != new_prev:
            # Prevhash changed — winner identity unknown from notify alone.
            ev, detail = (
                "new_block",
                "Another block has been detected on the network. "
                "Preparing the next mining round.",
            )
        else:
            ev, detail = (
                "new_job",
                "The pool has updated your mining work.",
            )
        if self._scratch is not None:
            self._scratch.interrupt_active("new job")
        self._ensure_game_board(
            force_new=True,
            reason="clean_jobs" if clean else "new job same tip",
            reset_history=True,
            keep_prior_boards=False,
        )
        # Keep semantic event after board_ready (UI resets tiles + animates).
        self._set_game_event(ev, detail)
        self._game_wake.set()
        self._emit()

    def _bump_game_board_extranonce(self, *, manual: bool = False) -> bool:
        from audit.work_family import family_from_job

        with self._job_lock:
            job = self._job
            if job is None or not job.accept_new_work():
                return False
            job.bump_extranonce2(work_family_id=family_from_job(job))
        ok = self._ensure_game_board(
            force_new=True,
            reason="manual new board" if manual else "extranonce2 bump",
            keep_prior_boards=True,
        )
        if not ok:
            return False
        self._set_game_event(
            "nonce_space_done" if not manual else "board_ready",
            (
                "New board — fresh 2³² nonce space (previous boards kept)."
                if manual
                else "Nonce Space Completed! Preparing a new search space..."
            ),
        )
        if not manual:
            self._emit()
        return True

    def _try_game_gpu_slice(self) -> bool:
        """
        Run at most one Game Mode GPU micro-batch.
        Returns True if GPU work ran (counts toward 50/50 share).
        """
        if not self._game_gpu_active() or self._gpu is None:
            return False
        from mining.best_hash import difficulty_from_hash_int, hash_be_hex_to_int
        from mining.job import WorkBatch

        with self._job_lock:
            job = self._job
            job_ok = job is not None and job.accept_new_work()
        if not job_ok:
            if not self._auto_enabled:
                self.stats.status = "Game Mode — waiting for pool job (no hashing yet)."
                self._emit()
            return False

        if self._scratch is None:
            self._ensure_game_board(force_new=True, reason="initial board")
        scratch = self._scratch
        if scratch is None:
            return False
        if scratch.all_completed():
            self._bump_game_board_extranonce()
            return False

        chunk = scratch.next_chunk()
        if chunk is None:
            if not self._auto_enabled:
                self.stats.status = (
                    "Game Mode — pick a tile to mine (GPU idle until then)."
                )
                self._publish_game_metrics()
                self._emit()
                self._game_wake.wait(0.25)
                self._game_wake.clear()
            return False

        with self._job_lock:
            live = self._job
            if live is None or not live.accept_new_work():
                scratch.interrupt_active("job gone")
                return False
            session = int(self._stratum.session_id) if self._stratum else 0
            snap = live.snapshot(
                validity_epoch=self._work_epoch, session_id=session
            )
        if not scratch.board.matches_snapshot(
            session_id=snap.session_id,
            job_id=snap.job_id,
            header_prefix=snap.header_prefix,
            extranonce2_hex=snap.extranonce2_hex,
        ):
            # Dual mode: prefer live EN2 — rebuild a board for current job.
            scratch.invalidate_board("stale board vs live job")
            self._ensure_game_board(force_new=True, reason="stale board")
            return False

        work = WorkBatch(
            snapshot=snap,
            start_nonce=int(chunk.start_nonce),
            count=int(chunk.count),
            logical_start=int(chunk.start_nonce),
            strategy="sequential",
            affine_a=1,
            affine_b=0,
            seed_fp="game",
        )
        track_best = (
            self.network_id in SUPPORTED_BEST_HASH_NETWORKS
            and self._best_hash_mode() == "gpu_batch"
            and self._best_store_ok
        )
        self._game_active_tile_id = int(chunk.tile_id)
        dual = self._auto_enabled and self._game_gpu_active()
        self.stats.status = (
            f"{'Auto+Game' if dual else 'Game Mode'} — tile {chunk.tile_id} "
            f"[{chunk.start_nonce}…{chunk.start_nonce + chunk.count})"
        )
        try:
            t0 = time.perf_counter()
            result = self._gpu.search(
                midstate=snap.midstate,
                header80=work.header80(),
                share_target=snap.share_target_value,
                start_nonce=work.start_nonce,
                count=work.count,
                track_best=track_best,
                strategy=0,
                aff_a=1,
                aff_b=0,
            )
            if result.truncated:
                self._log_event(
                    f"Game GPU hit buffer full raw={result.raw_hit_count} "
                    f"— rescan with network target"
                )
                net_res = self._gpu.search(
                    midstate=snap.midstate,
                    header80=work.header80(),
                    share_target=snap.network_target_value,
                    start_nonce=work.start_nonce,
                    count=work.count,
                    max_hits=64,
                    track_best=False,
                    strategy=0,
                    aff_a=1,
                    aff_b=0,
                )
                result.hits = list(dict.fromkeys(net_res.hits + result.hits))
            t1 = time.perf_counter()
        except Exception as exc:
            scratch.apply_chunk_progress(chunk, scanned=0, interrupted=True)
            self.stats.status = f"Game GPU scan error: {exc}"
            self._game_active_tile_id = None
            self._emit()
            return False

        if self._stop.is_set():
            scratch.apply_chunk_progress(chunk, scanned=0, interrupted=True)
            self._game_active_tile_id = None
            return False

        if not scratch.board.matches_snapshot(
            session_id=snap.session_id,
            job_id=snap.job_id,
            header_prefix=snap.header_prefix,
            extranonce2_hex=snap.extranonce2_hex,
        ) or (
            self._scratch is not None
            and self._scratch.board.board_id != chunk.board_id
        ):
            self._game_active_tile_id = None
            return False

        scanned = int(result.scanned)
        batch_s = max(0.0, t1 - t0)
        self._game_gpu_s += batch_s
        self.stats.total_hashes += scanned
        self.stats.last_scanned = scanned
        self.stats.last_kernel_ms = batch_s * 1000.0
        if batch_s > 0:
            self.stats.hashrate = scanned / batch_s

        share_n = 0
        for nonce in result.hits:
            if self._stop.is_set():
                break
            verified = snap.verify_nonce(int(nonce))
            if not verified:
                continue
            share_n += 1
            self._handle_verified(work, verified)

        best_diff = None
        best_hex = result.best_hash_be_hex
        best_nonce = result.best_nonce
        if best_hex:
            try:
                best_diff = difficulty_from_hash_int(hash_be_hex_to_int(best_hex))
            except (TypeError, ValueError):
                best_diff = None
        if track_best and best_hex and best_nonce is not None:
            self._track_gpu_best_from_result(snap, result)

        interrupted = self._stop.is_set() or self.stats.paused_thermal
        was_done = False
        try:
            was_done = scratch.get_tile(int(chunk.tile_id)).state.value == "COMPLETED"
        except Exception:
            was_done = False
        tile_res = scratch.apply_chunk_progress(
            chunk,
            scanned=scanned,
            processing_time_s=batch_s,
            best_difficulty=best_diff,
            best_hash_be_hex=best_hex,
            best_nonce=int(best_nonce) if best_nonce is not None else None,
            share_candidates=share_n,
            interrupted=interrupted,
        )
        if tile_res.state.value == "COMPLETED" and not was_done:
            self._game_tiles_completed_session += 1
        self._game_active_tile_id = None
        update = {
            "tile_id": tile_res.tile_id,
            "state": tile_res.state.value,
            "best_difficulty": tile_res.best_difficulty,
            "best_hash_be_hex": tile_res.best_hash_be_hex,
            "hashes": tile_res.hashes,
            "share_candidates": tile_res.share_candidates,
            "accepted": tile_res.accepted,
            "rejected": tile_res.rejected,
            "processing_time_s": tile_res.processing_time_s,
            "start_nonce": tile_res.start_nonce,
            "end_nonce": tile_res.end_nonce,
            "next_nonce": tile_res.next_nonce,
            "board_id": scratch.board.board_id,
            "extranonce2": scratch.board.extranonce2_hex,
        }
        self._publish_game_metrics(tile_update=update)
        self._emit()
        if tile_res.state.value == "COMPLETED" and scratch.all_completed():
            self._bump_game_board_extranonce()
        return True

    def _track_gpu_best_from_result(self, snap, result) -> None:
        """Reuse existing GPU best path from a SearchResult (game micro-batch)."""
        try:
            self._track_best_hash(snap, result, [])
        except Exception:
            log.exception("game gpu best track")

    def _run_mainnet(self) -> None:
        self._mining_address = self.address
        self._donation_active = False
        if self._game_enabled and not self._auto_enabled:
            self.update_idle_options(enabled=False)
            self.stats.status = (
                "Game Mode — connecting to pool (no hashing until you pick a tile)."
            )
            self._emit()
        self._start_stratum_for(self._mining_address)
        if is_effectively_enabled(self.app_donation, self.network_id):
            pct = float(self.app_donation.get("percent") or 0)
            self._log_event(
                f"{APP_NAME} donation on: {pct:g}% time slices — "
                "block found in slice sends full reward to donation address."
            )
        self._mine_loop()

    def _authorize_user(self, address: str) -> str:
        ident = self._profile.pool_identity(address)
        ep = self._pool_endpoint
        if ep is None:
            return self._profile.username_for(address)
        return ep.render_username(ident)

    def _pool_conn(self) -> tuple[str, int, str]:
        ep = self._pool_endpoint
        if ep is None:
            return (
                self._profile.stratum_host,
                int(self._profile.stratum_port),
                self._profile.password or "x",
            )
        return ep.host, int(ep.port), ep.password or "x"

    def _start_stratum_for(self, address: str) -> None:
        with self._motor_ops:
            if self._motor_start_blocked():
                return
            user = self._authorize_user(address)
            host, port, password = self._pool_conn()
            use_tls = bool(self._pool_endpoint and self._pool_endpoint.transport == "tls")
            self._stratum = StratumClient(
                host=host,
                port=port,
                on_job=self._on_job,
                on_difficulty=self._on_difficulty,
                on_status=self._on_stratum_status,
                on_submit_result=self._on_submit_result,
                suggest_difficulty=1.0,
                password=password,
                use_tls=use_tls,
            )
            self._stratum.start(user)
            self.stats.payout_address = address
            log_fields = safe_pool_log_fields(
                host=host,
                port=port,
                transport="tls" if use_tls else "tcp",
                username=user,
                password=password,
            )
            self._log_event(
                f"Network={self._profile.id} stratum={log_fields['host']}:"
                f"{log_fields['port']} user={str(user)[:24]}…"
                + (" [donation slice]" if self._donation_active else "")
            )
            self._log_event(
                "mining.suggest_difficulty(1) will be sent (after authorize). "
                "Effective share difficulty is set only by server mining.set_difficulty."
            )

    def _desired_donation_active(self) -> bool:
        # Manuel Donate diyalo u; madencilik adresine y nlendirme yok
        return False

    def _sync_donation_slice(self) -> None:
        """Native: on slice change reconnect stratum to donation/user address."""
        if self.test_mode or self._profile.engine_kind != "native_sha256d":
            return
        if self._motor_start_blocked():
            return
        want = self._desired_donation_active()
        if want == self._donation_active:
            self.stats.donation_active = self._donation_active
            return
        daddr = donation_address_for(self.app_donation, self.network_id)
        target = daddr if want else self.address
        self._log_event(
            "Donation slice OPEN — reward to donation address."
            if want
            else "Donation slice closed — back to user address."
        )
        with self._motor_ops:
            if self._motor_start_blocked():
                return
            if self._stratum:
                try:
                    self._stratum.stop()
                except Exception:
                    pass
                self._stratum = None
            with self._job_lock:
                self._invalidate_all_jobs("donation slice transition")
                self._job = None
                # _start_stratum_for kendi motor_ops al r (RLock)
            self._start_stratum_for(target)
            if self._stratum is None:
                return
            self._donation_active = want
            self._mining_address = target
            self.stats.donation_active = want
            self.stats.payout_address = target

    def _run_test_mode(self) -> None:
        self.stats.test_mode = True
        self.stats.connected = True
        self.stats.difficulty = 0.0001
        self.stats.status = "TEST MODE: does not produce real BTC. Local low-difficulty scan."
        self._emit()

        genesis = bytes.fromhex(
            "0100000000000000000000000000000000000000000000000000000000000000"
            "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
            "4b1e5e4a29ab5f49ffff001d1dac2b7c"
        )
        job = MiningJob(
            job_id="testjob",
            prevhash="0" * 64,
            coinb1="",
            coinb2="",
            merkle_branches=[],
            version="01000000",
            nbits="1d00ffff",
            ntime="29ab5f49",
            clean_jobs=True,
            extranonce1="",
            extranonce2_size=4,
            difficulty=0.0001,
            generation=1,
        )
        job._merkle_root = bytes(32)
        job._header_prefix = genesis[:76]
        job._midstate = midstate_from_header(genesis)
        job._midstate_key = genesis[:64]
        job._tail = genesis[64:76]
        job.nonce = 0
        self._job_gen = 1
        with self._job_lock:
            self._job = job
        self._mine_loop()

    def _on_stratum_status(self, text: str) -> None:
        self.stats.status = text
        self.stats.connected = bool(self._stratum and self._stratum.connected)
        prev_session = self.stats.session_id
        if self._stratum:
            self.stats.session_id = self._stratum.session_id
            # Oturum de i imi / kopma t m eski batch'ler ge ersiz
        if self._stratum and self._stratum.session_id != prev_session and prev_session:
            with self._job_lock:
                self._invalidate_all_jobs(
                    f"oturum {prev_session}→{self._stratum.session_id}"
                )
                self._job = None
            if self._work_ledger is not None and self._stratum.subscribed:
                self._work_ledger.on_subscribe(
                    session_id=int(self._stratum.session_id),
                    extranonce1=str(self._stratum.extranonce1 or ""),
                    extranonce2_size=int(self._stratum.extranonce2_size or 4),
                )
        elif "connection error" in text.lower() or "connection lost" in text.lower() or "disconnected" in text.lower():
            with self._job_lock:
                self._invalidate_all_jobs("connection lost")
                self._job = None
        if (
            self._work_ledger is not None
            and self._stratum
            and self._stratum.subscribed
            and self._stratum.extranonce1
            and "subscribed" in text.lower()
        ):
            self._work_ledger.on_subscribe(
                session_id=int(self._stratum.session_id),
                extranonce1=str(self._stratum.extranonce1 or ""),
                extranonce2_size=int(self._stratum.extranonce2_size or 4),
            )
        self._emit()

    def _on_difficulty(self, diff: float) -> None:
        new_diff = float(diff)
        self._pending_difficulty = new_diff
        self.stats.difficulty = new_diff
        self.stats.server_difficulty = new_diff
        self.stats.pending_difficulty = new_diff
        with self._job_lock:
            if self._job and self._job.accept_new_work():
                old = float(self._job.difficulty)
                self._job.difficulty = new_diff
                active_id = self._job.job_id
                notify_diff = float(self._job.diff_at_notify)
            else:
                old = None
                active_id = None
                notify_diff = None
        if self._stratum:
            self.stats.stratum_wire_log = list(self._stratum.wire_log[:30])
        if active_id:
            self._log_event(
                f"Server mining.set_difficulty={new_diff} → active_job={active_id} "
                f"work_diff {old}→{new_diff} (diff_at_notify={notify_diff} fixed; "
                f"locked batch in snapshot). suggested={self.stats.suggest_difficulty_sent}"
            )
        else:
            self._log_event(
                f"Sunucu mining.set_difficulty={new_diff} "
                f"(no active allocation). suggested={self.stats.suggest_difficulty_sent}"
            )
        if self._audit_live is not None:
            self._audit_live.on_difficulty(new_diff)
        self._emit()

    def _on_job(self, params: list, clean: bool) -> None:
        assert self._stratum is not None
        self._job_gen += 1
        gen = self._job_gen
        diff = float(self._pending_difficulty or self._stratum.difficulty or 1.0)
        job = job_from_notify(
            params,
            self._stratum.extranonce1,
            self._stratum.extranonce2_size,
            diff,
            gen,
        )
        from audit.work_family import family_from_job
        from mining.search_strategy import SearchStrategy

        job.configure_search_strategy(
            SearchStrategy(self.search_strategy()),
            work_family_id=family_from_job(job),
        )

        # Coinbase payout validation — profile flags from validation profile when set
        active_addr = self._mining_address or self.address
        vprof = get_validation_profile(
            (self._pool_endpoint.validation_profile_id if self._pool_endpoint else "")
            or ""
        )
        if self._pool_endpoint is None or self._pool_endpoint.mode == "default":
            fee_num = self._profile.coinbase_pool_fee_num
            fee_den = self._profile.coinbase_pool_fee_den
            enforce = self._profile.coinbase_enforce_fee_split
            require_user = self._profile.coinbase_require_user_payout
        else:
            fee_num = vprof.fee_num
            fee_den = vprof.fee_den
            enforce = vprof.enforce_fee_split
            require_user = vprof.require_user_payout
        payout = verify_job_coinbase_payout(
            coinb1=job.coinb1,
            coinb2=job.coinb2,
            extranonce1=job.extranonce1,
            extranonce2_hex=job.extranonce2_hex(),
            payout_address=active_addr,
            pool_fee_num=fee_num,
            pool_fee_den=fee_den,
            enforce_fee_split=enforce,
            require_user_payout=require_user,
        )
        self.stats.coinbase_status = payout.message
        if payout.stop_mining:
            self._coinbase_ok = False
            with self._job_lock:
                if self._job:
                    self._job.mark_invalidated()
                job.mark_invalidated()
                self._job = None
            self.stats.status = f"Coinbase error — mining stopped: {payout.message}"
            self._log_event(self.stats.status)
            self._emit()
            return

        self._coinbase_ok = True
        if payout.amount_independently_verified:
            self._log_event(f"Coinbase: {payout.message}")
        else:
            self._log_event(f"Coinbase: {payout.message}")

        with self._job_lock:
            if clean:
                # T m nceki i ler + epoch yaln z son job yetmez
                self._invalidate_all_jobs(f"clean_jobs=true yeni={job.job_id}")
            else:
                for j in list(self._known_jobs):
                    j.mark_superseded()
                if self._job is not None:
                    self._log_event(
                        f"clean_jobs=false → old jobs superseded "
                        f"(epoch={self._work_epoch} same; in-flight snapshot may still submit)"
                    )
            self._known_jobs.append(job)
            self._known_jobs = self._known_jobs[-32:]
            self._job = job

        self.stats.difficulty = diff
        self.stats.pending_difficulty = self._pending_difficulty
        self.stats.current_job_id = job.job_id
        self.stats.session_id = self._stratum.session_id
        self.stats.status = f"New job: {job.job_id} (clean_jobs={clean})"
        self.stats.stratum_wire_log = list(self._stratum.wire_log[:30])
        self._log_event(
            f"New job: id={job.job_id} clean={clean} epoch={self._work_epoch} "
            f"session={self._stratum.session_id} "
            f"diff_at_notify={job.diff_at_notify} "
            f"en1={job.extranonce1} en2_size={job.extranonce2_size} "
            f"ntime={job.ntime} nbits={job.nbits} branches={len(job.merkle_branches)}"
        )
        if self._game_enabled:
            self._game_on_new_job(job, clean)
        if self._audit_live is not None:
            self._audit_live.on_notify(job, clean)
        if self._work_ledger is not None:
            if self._stratum and self._stratum.subscribed:
                # Ensure subscribe captured even if status text differed
                self._work_ledger.on_subscribe(
                    session_id=int(self._stratum.session_id),
                    extranonce1=str(self._stratum.extranonce1 or ""),
                    extranonce2_size=int(self._stratum.extranonce2_size or 4),
                )
            t_led = time.perf_counter()
            self._work_ledger.on_notify(
                job,
                clean,
                session_id=int(self._stratum.session_id) if self._stratum else 0,
                payout_address=self._mining_address or self.address or "",
            )
            self._work_ledger.note_overhead_s(time.perf_counter() - t_led)
        self._emit()

    def _log_event(self, text: str) -> None:
        line = f"{time.strftime('%H:%M:%S')}  {text}"
        self.stats.event_log.insert(0, line)
        self.stats.event_log = self.stats.event_log[:100]

    def _on_submit_result(self, ok: bool, msg: str, meta: Any) -> None:
        stamp = time.strftime("%H:%M:%S")
        req_id = meta.get("id") if isinstance(meta, dict) else None
        session_id = meta.get("session_id") if isinstance(meta, dict) else None
        outcome_unknown = bool(isinstance(meta, dict) and meta.get("outcome_unknown"))
        if session_id is None and self._stratum and not outcome_unknown:
            session_id = self._stratum.session_id

        entry = None
        if req_id is not None and session_id is not None:
            with self._submit_lock:
                entry = self._pending_submits.pop((int(session_id), int(req_id)), None)

        result = meta.get("result") if isinstance(meta, dict) else None
        error = meta.get("error") if isinstance(meta, dict) else None
        really_ok = (
            not outcome_unknown
            and bool(ok)
            and error is None
            and result is True
        )

        if entry is None:
            self._log_event(
                f"Pool response unmatched id={req_id} session={session_id} "
                f"ok={really_ok} unknown={outcome_unknown} msg={msg}"
            )
            if self._stratum:
                self.stats.submit_rpc_log = list(self._stratum.submit_log[:20])
            self._emit()
            return

        entry["pending"] = False
        entry["pool_time"] = stamp
        if outcome_unknown:
            # Ba lant koptu / cevap yok pool reddi de il
            entry["status"] = "outcome_unknown"
            entry["pool_ok"] = None
            entry["outcome_unknown"] = True
            self.stats.status = "Share outcome unknown (connection; not a pool reject)."
            self._log_event(
                f"Pool: OUTCOME UNKNOWN id={req_id} session={session_id} "
                f"job={entry.get('job_id')} nonce={entry.get('nonce_hex')}"
            )
        elif really_ok:
            if entry.get("app_donation"):
                self.stats.app_donation_shares += 1
                entry["status"] = "donation share accepted (not user earnings)"
                entry["pool_ok"] = True
                self.stats.status = f"{APP_NAME} donation share accepted."
                self._log_event(
                    f"Pool: DONATION ACCEPTED id={req_id} session={session_id} "
                    f"job={entry.get('job_id')} (not user accepted)"
                )
            else:
                self.stats.accepted += 1
                entry["status"] = "pool_response (accepted; not a payout)"
                entry["pool_ok"] = True
                self.stats.status = (
                    f"Share accepted — this is not a {self._profile.display_name} payout."
                )
                self._log_event(
                    f"Pool: ACCEPTED id={req_id} session={session_id} "
                    f"job={entry.get('job_id')} nonce={entry.get('nonce_hex')} (not a payout)"
                )
                self._track_last_accepted(entry)
                self._track_accepted_best(entry)
                if (
                    self._game_enabled
                    and self._scratch is not None
                    and entry.get("game_tile_id") is not None
                ):
                    self._scratch.note_share_outcome(
                        int(entry["game_tile_id"]), accepted=True
                    )
                if self._audit_live is not None:
                    try:
                        sd = float(entry.get("difficulty") or 0) or None
                    except (TypeError, ValueError):
                        sd = None
                    self._audit_live.on_submit_result(
                        accepted=True, rejected=False, share_difficulty=sd
                    )
        else:
            self.stats.rejected += 1
            entry["status"] = f"pool_response (rejected: {msg})"
            entry["pool_ok"] = False
            self.stats.status = f"Share rejected: {msg}"
            self._log_event(
                f"Pool: REJECTED id={req_id} session={session_id} — {msg}"
            )
            if (
                self._game_enabled
                and self._scratch is not None
                and entry.get("game_tile_id") is not None
            ):
                self._scratch.note_share_outcome(
                    int(entry["game_tile_id"]), accepted=False
                )
            if self._audit_live is not None:
                try:
                    sd = float(entry.get("difficulty") or 0) or None
                except (TypeError, ValueError):
                    sd = None
                self._audit_live.on_submit_result(
                    accepted=False, rejected=True, share_difficulty=sd
                )

        if entry.get("block_candidate") and not entry.get("test_mode"):
            if outcome_unknown:
                entry["chain_status"] = STATUS_PENDING_VERIFY
            elif really_ok:
                entry["chain_status"] = STATUS_PENDING_VERIFY
            else:
                entry["chain_status"] = STATUS_POOL
            self._persist_block(entry)
            if not outcome_unknown and not entry.get("app_donation"):
                self._explorer.watch(entry)

                # Son blok aday : yaln z ger ek blok kayd + hash kimli i (submit_id ak mas yetmez)
        if (
            entry.get("block_candidate") is True
            and not entry.get("app_donation")
            and entry.get("hash")
            and self.stats.last_block
            and self.stats.last_block.get("block_candidate") is True
            and self.stats.last_block.get("hash") == entry.get("hash")
            and self.stats.last_block.get("submit_id") == entry.get("submit_id")
            and self.stats.last_block.get("session_id") == entry.get("session_id")
        ):
            self.stats.last_block = dict(entry)
            for i, item in enumerate(self.stats.block_candidates):
                if item.get("hash") == entry.get("hash"):
                    self.stats.block_candidates[i] = dict(entry)
                    break
                    # Normal share asla last_block'u de i tirmez
        if (
            not entry.get("block_candidate")
            and self.stats.last_share
            and self.stats.last_share.get("submit_id") == entry.get("submit_id")
            and self.stats.last_share.get("session_id") == entry.get("session_id")
            and (
                not entry.get("hash")
                or self.stats.last_share.get("hash") == entry.get("hash")
            )
        ):
            self.stats.last_share = dict(entry)

        if self._stratum:
            self.stats.submit_rpc_log = list(self._stratum.submit_log[:20])
        self._emit()

    def _on_explorer_update(self, rec: dict) -> None:
        h = rec.get("hash")
        nid = str(rec.get("network_id") or "").strip().lower()
        # Durmu oturum: yaln z disk; canl UI/listeye yazma
        ui_live = (
            not self._stop.is_set()
            and not self._stopping
            and (
                self._preparing
                or (self._thread is not None and self._thread.is_alive())
            )
        )
        # Ba ka a a ait gecikmi yan t aktif oturum listesine kar mas n
        if nid and nid != str(self.network_id or "").strip().lower():
            self._persist_block(dict(rec))
            return
        if not ui_live:
            self._persist_block(dict(rec))
            return
        updated = False
        for i, item in enumerate(self.stats.block_candidates):
            item_nid = str(item.get("network_id") or self.network_id or "").strip().lower()
            if item.get("hash") == h and item_nid == nid:
                self.stats.block_candidates[i] = {**item, **rec}
                updated = True
                if (
                    self.stats.last_block
                    and self.stats.last_block.get("hash") == h
                    and str(self.stats.last_block.get("network_id") or "").strip().lower()
                    == nid
                ):
                    self.stats.last_block = dict(self.stats.block_candidates[i])
                break
        if updated:
            self._persist_block(self.stats.block_candidates[i])
            st = rec.get("chain_status")
            self._log_event(
                f"Explorer [{nid}]: hash={str(h)[:16]}… status={st} {rec.get('chain_detail')}"
            )
            self._emit()

    def _persist_block(self, entry: dict) -> None:
        if entry.get("test_mode"):
            return
        entry = dict(entry)
        entry.setdefault("network_id", self.network_id)
        self._block_store.enqueue_upsert(entry)
        if self._block_store.last_error:
            self.stats.block_store_error = self._block_store.last_error
            self._log_event(self._block_store.last_error)

    def _thermal_gate(self) -> bool:
        """
        Mandatory thermal guard for every engine path.
        Over pause_temp → pause all hashing (native / Game / XMRig / Rigel callers).
        """
        if self._resolved_gpu_bus:
            from monitor.gpu_devices import temperature_for_bus

            temp, src = temperature_for_bus(self._resolved_gpu_bus)
            if src:
                self.stats.thermal_source = src
        else:
            temp = self._temp.read_celsius()
        self.stats.gpu_temp = temp
        if temp is None:
            self.stats.temp_readable = False
            # Sensor loss must never resume / continue hashing.
            self._paused = True
            self.stats.paused_thermal = True
            self.stats.status = (
                "Temperature unreadable — all mining paused (thermal required)."
            )
            if not getattr(self, "_thermal_unreadable_logged", False):
                self._log_event(self.stats.status)
                self._thermal_unreadable_logged = True
            return False
        self._thermal_unreadable_logged = False
        self.stats.temp_readable = True
        if self._paused:
            if temp <= self.resume_temp:
                self._paused = False
                self.stats.paused_thermal = False
                self.stats.status = f"Temperature {temp}°C — resumed."
                self._log_event(
                    f"Thermal: cooled ({temp}°C ≤ {self.resume_temp}°C) — mining resumed"
                )
            else:
                self.stats.paused_thermal = True
                return False
        elif temp >= self.pause_temp:
            self._paused = True
            self.stats.paused_thermal = True
            self.stats.status = (
                f"Temperature {temp}°C — all mining paused "
                f"(threshold {self.pause_temp}°C)."
            )
            self._log_event(
                f"Thermal: paused ({temp}°C ≥ {self.pause_temp}°C) — "
                "all mining processes paused until cooled"
            )
            return False
        return True

    def _mine_loop(self) -> None:
        assert self._gpu is not None
        while not self._stop.is_set():
            self._sync_donation_slice()

            if not self._coinbase_ok and not self.test_mode:
                self._stop.wait(0.5)
                self._emit()
                continue

            if not self._thermal_gate():
                # Thermal outranks auto-idle — do not hash; stratum stays up.
                if self._game_gpu_active() and self._scratch is not None:
                    self._scratch.interrupt_active("thermal pause")
                self.stats.paused_idle = False
                self._set_activity_ui("")
                self._emit()
                self._interruptible_wait(0.5)
                continue

            # Game-only (board open): never run allocate_batch auto path.
            if self._game_enabled and not self._auto_enabled:
                if self._game_board_open:
                    self._try_game_gpu_slice()
                else:
                    self._interruptible_wait(0.25)
                continue

            idle_state = self._eval_idle_policy()
            self._idle_scale = float(idle_state.scale)
            auto_on = idle_state.mode != "off"
            if auto_on and idle_state.scale <= 0.0:
                self.stats.paused_idle = True
                self.stats.hashrate = 0.0
                self._hash_window.clear()
                self._set_activity_ui("Using PC · Mining paused")
                self.stats.status = (
                    "Using PC — hashing paused. Pool connection and jobs still update."
                )
                self._emit()
                # Dual mode: Game may still hash while auto is idle-paused.
                if self._game_gpu_active():
                    self._try_game_gpu_slice()
                else:
                    self._interruptible_wait(0.25)
                continue
            self.stats.paused_idle = False
            if auto_on:
                if idle_state.mode == "idle":
                    self._set_activity_ui("AFK · Duty-cycle scaled")
                else:
                    self._set_activity_ui("Using PC · Duty-cycle scaled")
            else:
                self._set_activity_ui("")

            # Dual Auto+Game (board open): ~50/50 Intensity by GPU seconds.
            if self._game_gpu_active() and self._auto_enabled:
                if self._game_gpu_s <= self._auto_gpu_s:
                    if self._try_game_gpu_slice():
                        continue

            if not self._auto_enabled:
                self._interruptible_wait(0.1)
                continue

            with self._job_lock:
                job = self._job
                if job is None or not job.accept_new_work():
                    job = None

            if job is None:
                if self._game_gpu_active():
                    self._try_game_gpu_slice()
                else:
                    self._interruptible_wait(0.1)
                    self._emit()
                continue

            # Auto-idle OFF or S>=1: exact historical ladder. Partial S: full
            # intensity batch + adaptive sleep from measured T (base sleep once).
            # Board closed / no Game GPU → full Intensity to Automatic.
            batch_n, base_sleep = intensity_batch_sleep(self.intensity)
            with self._job_lock:
                if self._job is not job or not job.accept_new_work():
                    continue
                epoch = self._work_epoch
                session = self._stratum.session_id if self._stratum else 0
                work = job.allocate_batch(
                    batch_n, validity_epoch=epoch, session_id=session
                )

            if work is None:
                self._interruptible_wait(0.01)
                continue

            snap = work.snapshot
            track_best = (
                self.network_id in SUPPORTED_BEST_HASH_NETWORKS
                and self._best_hash_mode() == "gpu_batch"
                and self._best_store_ok
            )
            try:
                t0 = time.perf_counter()
                audit = self._audit_live
                hist = None
                if audit is not None and self.network_id in SUPPORTED_BEST_HASH_NETWORKS:
                    if not self._gpu.ensure_audit_kernel():
                        self._log_event(
                            "Live audit: OpenCL audit kernel unavailable — "
                            "falling back to production search (histogram skipped)"
                        )
                        sk = self._strategy_kernel_args(work)
                        result = self._gpu.search(
                            midstate=snap.midstate,
                            header80=work.header80(),
                            share_target=snap.share_target_value,
                            start_nonce=work.start_nonce,
                            count=work.count,
                            track_best=track_best,
                            **sk,
                        )
                    else:
                        sk = self._strategy_kernel_args(work)
                        result, hist = self._gpu.search_audit(
                            midstate=snap.midstate,
                            header80=work.header80(),
                            share_target=snap.share_target_value,
                            start_nonce=work.start_nonce,
                            count=work.count,
                            track_best=track_best,
                            **sk,
                        )
                        from audit.work_family import work_family_id
                        from mining.best_hash import verify_best_candidate

                        cpu_fail = False
                        if result.best_hash_be_hex and result.best_nonce is not None:
                            hdr = snap.header_for_nonce(int(result.best_nonce))
                            if not verify_best_candidate(hdr, result.best_hash_be_hex):
                                cpu_fail = True
                        audit.on_batch(
                            family_id=work_family_id(
                                prevhash=snap.prevhash,
                                coinb1=snap.coinb1,
                                coinb2=snap.coinb2,
                                merkle_branches=snap.merkle_branches,
                                version=snap.version,
                                nbits=snap.nbits,
                                ntime=snap.ntime,
                                extranonce1=snap.extranonce1,
                                extranonce2_size=snap.extranonce2_size,
                            ),
                            extranonce2_hex=snap.extranonce2_hex,
                            header_prefix=snap.header_prefix,
                            start_nonce=work.start_nonce,
                            count=work.count,
                            result=result,
                            hist=hist,
                            t0=t0,
                            cpu_verify_failed=cpu_fail,
                        )
                else:
                    sk = self._strategy_kernel_args(work)
                    result = self._gpu.search(
                        midstate=snap.midstate,
                        header80=work.header80(),
                        share_target=snap.share_target_value,
                        start_nonce=work.start_nonce,
                        count=work.count,
                        track_best=track_best,
                        **sk,
                    )
                # Tampon dolduysa a hedefiyle ikinci tarama blok aday kayb n telafi
                if result.truncated:
                    self._log_event(
                        f"GPU hit tamponu doldu raw={result.raw_hit_count} "
                        f"cap={len(result.hits)} — rescan with network target"
                    )
                    sk = self._strategy_kernel_args(work)
                    net_res = self._gpu.search(
                        midstate=snap.midstate,
                        header80=work.header80(),
                        share_target=snap.network_target_value,
                        start_nonce=work.start_nonce,
                        count=work.count,
                        max_hits=64,
                        track_best=False,
                        **sk,
                    )
                    merged = list(dict.fromkeys(net_res.hits + result.hits))
                    result.hits = merged
                t1 = time.perf_counter()
                kernel_ms = (t1 - t0) * 1000.0
            except Exception as exc:
                self.stats.status = f"GPU scan error: {exc}"
                self._emit()
                self._interruptible_wait(1.0)
                continue

            batch_time_s = max(0.0, t1 - t0)
            self._auto_gpu_s += batch_time_s
            if auto_on and idle_state.scale < 1.0:
                self._ema_batch_s = update_ema(self._ema_batch_s, batch_time_s)
                t_for_duty = float(self._ema_batch_s or batch_time_s)
                sleep_s = adaptive_duty_sleep(
                    t_for_duty, base_sleep, idle_state.scale
                )
            else:
                # OFF or S==1: historical base sleep only (no adaptive formula).
                sleep_s = float(base_sleep)
                self._ema_batch_s = None

            scanned = int(result.scanned)
            self.stats.total_hashes += scanned
            try:
                self.stats.lifetime_attempts = add_lifetime_attempts(
                    self.network_id, scanned
                )
            except OSError:
                pass
            if self._work_ledger is not None:
                # Family id already captured at notify; avoid re-hashing per batch.
                t_led = time.perf_counter()
                strat = str(work.strategy or "sequential")
                use_logical = strat == "randomized"
                # Reverse: contiguous physical [base-count+1, base+1)
                phys_start = int(work.start_nonce)
                if strat == "reverse":
                    phys_start = (int(work.start_nonce) - int(work.count) + 1) & 0xFFFFFFFF
                self._work_ledger.on_gpu_batch_completed(
                    job_id=str(snap.job_id),
                    work_family_id="",
                    extranonce2_hex=str(snap.extranonce2_hex),
                    start_nonce=phys_start if not use_logical else int(work.start_nonce),
                    allocated_count=int(work.count),
                    scanned=int(scanned),
                    kernel_s=(kernel_ms / 1000.0) if kernel_ms > 0 else 0.0,
                    strategy=strat,
                    seed_fp=str(work.seed_fp or ""),
                    logical_start=int(work.logical_start) if use_logical else None,
                )
                self._work_ledger.note_overhead_s(time.perf_counter() - t_led)
            self.stats.last_batch = batch_n
            self.stats.last_scanned = scanned
            self.stats.last_global = result.global_size
            self.stats.last_local = result.local_size
            self.stats.last_sleep_s = sleep_s
            self.stats.last_kernel_ms = kernel_ms

            self._hash_window.append((t0, t1, scanned))
            self._hash_window = [
                (a, b, n) for a, b, n in self._hash_window if t1 - a < 5.0
            ]
            self.stats.hashrate = rate_from_window(
                self._hash_window,
                last_kernel_s=(kernel_ms / 1000.0) if kernel_ms > 0 else 0.0,
            )
            if self._work_ledger is not None:
                self._work_ledger.note_hashrate(float(self.stats.hashrate or 0.0))

            with self._job_lock:
                cur_epoch = self._work_epoch
                cur_session = self._stratum.session_id if self._stratum else 0

            verified_list: list[dict] = []
            for nonce in result.hits:
                if not work.is_submittable(cur_epoch, cur_session):
                    self._log_event(
                        f"In-flight hit skipped (epoch/session) job={snap.job_id} "
                        f"nonce={nonce:08x} batch_epoch={work.validity_epoch} "
                        f"cur_epoch={cur_epoch}"
                    )
                    if self._work_ledger is not None:
                        self._work_ledger.on_inflight_aborted(1)
                    break
                verified = snap.verify_nonce(nonce)
                if verified:
                    # A hedefini sa layan sonu share filtresiyle elenmez
                    verified_list.append(verified)

                    # Blok adaylar nce
            verified_list.sort(
                key=lambda v: (0 if v.get("meets_network") else 1, int(v["nonce"]))
            )
            for verified in verified_list:
                self._handle_verified(work, verified)

            self._track_best_hash(snap, result, verified_list)
            self._emit()
            if sleep_s > 0:
                # Only abort long AFK duty waits when the user returns (→ Using PC).
                # Never abort while already in Using-PC mode — that skipped Active %
                # duty-cycle and made Active/AFK intensities feel reversed.
                self._interruptible_wait(
                    sleep_s,
                    abort_if_active=bool(
                        auto_on
                        and idle_state.mode == "idle"
                        and idle_state.scale < 1.0
                    ),
                )

    def _handle_verified(self, work: WorkBatch, verified: dict) -> None:
        snap = work.snapshot
        is_block = bool(verified.get("meets_network"))
        stamp = time.strftime("%H:%M:%S")
        # Submit alanlar yaln zca snapshot'tan
        nonce = int(verified["nonce"])
        nonce_hex = verified.get("nonce_hex") or nonce_to_submit_hex(nonce)
        job_id = str(snap.job_id)
        extranonce2 = str(snap.extranonce2_hex)
        ntime = str(snap.ntime)
        if (
            nonce_to_submit_hex(nonce) != nonce_hex
            or int(nonce_hex, 16) != nonce
            or verified.get("job_id") != job_id
            or verified.get("extranonce2") != extranonce2
            or verified.get("ntime") != ntime
        ):
            self._log_event(
                f"SUBMIT FIELD MISMATCH — not sent "
                f"nonce={nonce_hex} job={job_id}"
            )
            return

        rebuild = verified.get("rebuild") or {}
        header = rebuild.get("header") or verified.get("header") or b""
        header_hex = header.hex() if isinstance(header, (bytes, bytearray)) else str(header)

        entry: dict[str, Any] = {
            "time": stamp,
            "found_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "nonce": nonce,
            "nonce_hex": nonce_hex,
            "hash": verified.get("hash_be_hex") or verified.get("hash_hex"),
            "hash_le": verified.get("hash_le_hex"),
            "job_id": job_id,
            "extranonce2": extranonce2,
            "ntime": ntime,
            "difficulty": snap.difficulty,
            "diff_at_notify": snap.diff_at_notify,
            "nbits": snap.nbits,
            "share_target": snap.share_target_value,
            "merkle_root": verified.get("merkle_root_hex"),
            "header80": header_hex,
            "buffer_header_match": verified.get("buffer_header_match"),
            "payout_address": self._mining_address or self.address,
            "network_id": self.network_id,
            "app_donation": bool(self._donation_active),
            "share": True,
            "block_candidate": is_block,
            "meets_share": bool(verified.get("meets_share")),
            "meets_network": is_block,
            "status": STATUS_CANDIDATE if is_block else "share — submitting (not a payout)",
            "chain_status": STATUS_TEST if self.test_mode else (
                STATUS_CANDIDATE if is_block else ""
            ),
            "test_mode": self.test_mode,
            "pending": not self.test_mode,
            "session_id": work.session_id,
            "validity_epoch": work.validity_epoch,
            "submit_id": None,
            "game_tile_id": self._game_active_tile_id
            if self._game_enabled
            else None,
        }
        if entry["app_donation"]:
            entry["status"] = (
                "donation block candidate — submitting"
                if is_block
                else "donation share — submitting (not user earnings)"
            )

        if self.test_mode:
            self.stats.share_submit_count += 1
            entry["status"] = "TEST — not sent (server accepted not counted)"
            entry["pending"] = False
            entry["chain_status"] = STATUS_TEST
            if is_block and not entry.get("app_donation"):
                self.stats.block_candidate_count += 1
                self.stats.last_block = entry
                self.stats.block_candidates.insert(0, entry)
                self.stats.block_candidates = self.stats.block_candidates[:50]
            elif not entry.get("app_donation"):
                self.stats.last_share = entry
                self.stats.share_events.insert(0, entry)
                self.stats.share_events = self.stats.share_events[:50]
            self._log_event("TEST candidate — no mining.submit, accepted not incremented")
            return

            # Ge erlilik kontrol kay t send: ayn kilit (clean/session yar yok)
        with self._job_lock:
            if self._stratum is None:
                self._log_event(
                    f"No Stratum — share not sent job={job_id} nonce={nonce_hex}"
                )
                return
            cur_epoch = self._work_epoch
            cur_session = self._stratum.session_id
            if not work.is_submittable(cur_epoch, cur_session):
                self._log_event(
                    f"Invalid batch — not sent job={snap.job_id} "
                    f"epoch={work.validity_epoch}/{cur_epoch} "
                    f"session={work.session_id}/{cur_session}"
                )
                return
            if cur_session != work.session_id:
                self._log_event(
                    f"Session changed — stale batch not sent "
                    f"batch_session={work.session_id} cur={cur_session}"
                )
                return

            req_id = self._stratum.allocate_request_id()
            entry["submit_id"] = req_id
            entry["session_id"] = cur_session
            with self._submit_lock:
                self._pending_submits[(cur_session, req_id)] = entry

            try:
                self._stratum.submit_share(
                    self._mining_address or self.address,
                    job_id,
                    extranonce2,
                    ntime,
                    nonce_hex,
                    request_id=req_id,
                    expected_session_id=work.session_id,
                )
            except Exception as exc:
                with self._submit_lock:
                    self._pending_submits.pop((cur_session, req_id), None)
                entry["pending"] = False
                entry["status"] = "outcome_unknown"
                entry["outcome_unknown"] = True
                entry["pool_ok"] = None
                self._log_event(
                    f"mining.submit failed (outcome unknown): {exc}"
                )
                if is_block:
                    self._persist_block(entry)
                return

        self.stats.share_submit_count += 1
        self._log_event(
            f"mining.submit id={req_id} session={entry['session_id']} "
            f"job={job_id} en2={extranonce2} ntime={ntime} nonce={nonce_hex} "
            f"block={is_block}"
        )
        if self._audit_live is not None:
            try:
                sd = float(snap.difficulty)
            except (TypeError, ValueError):
                sd = None
            # submitted (outcome pending) — track max submitted difficulty
            self._audit_live.on_submit_result(
                accepted=False, rejected=False, share_difficulty=sd
            )

        # Submit sonras : UI listeleri + async disk (g nderimi geciktirmez)
        if entry.get("app_donation"):
            self._log_event(
                f"donation mining.submit id={req_id} block={is_block} "
                "(not added to user accepted/block lists)"
            )
            if is_block:
                self._persist_block(entry)
            self.stats.status = f"{APP_NAME} donation share sent."
        elif is_block:
            self.stats.block_candidate_count += 1
            self.stats.last_block = entry
            self.stats.block_candidates.insert(0, entry)
            self.stats.block_candidates = self.stats.block_candidates[:50]
            self.stats.status = (
                "BLOCK CANDIDATE sent. No payout shown until accepted on network."
            )
            self._log_event(
                f"BLOCK CANDIDATE nonce={nonce_hex} hash={entry.get('hash')} "
                "(no network confirm — not a payout)"
            )
            self._persist_block(entry)
            if self._block_store.last_error:
                self.stats.block_store_error = self._block_store.last_error
                self._log_event(self._block_store.last_error)
        else:
            self.stats.last_share = entry
            self.stats.share_events.insert(0, entry)
            self.stats.share_events = self.stats.share_events[:50]
            self.stats.status = "Share sent (not a payout)."

        self.stats.submit_rpc_log = list(self._stratum.submit_log[:20])
        self.stats.stratum_wire_log = list(self._stratum.wire_log[:30])
