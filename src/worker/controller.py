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
from networks.pool_input import safe_pool_log_fields
from networks.pool_resolve import resolve_pool
from networks.pool_types import ResolvedPoolEndpoint
from networks.pool_validation import get_validation_profile
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
    best_hash_mode: str = "gpu_batch"
    pool_display: str = ""
    pool_kind: str = "solo"
    pool_mode: str = "default"
    pool_banner: str = ""


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
        self.pause_temp = 65
        self.resume_temp = 55
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
        self.allow_mine_without_temp: bool = False
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

    def update_settings(self, intensity: int, pause_temp: int, resume_temp: int) -> None:
        self.intensity = max(1, min(10, int(intensity)))
        self.pause_temp = int(pause_temp)
        self.resume_temp = int(resume_temp)

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
        If temperature is unreadable and override is off, block mining.
        Returns True when the caller must abort the session start path.
        """
        if self.stats.temp_readable:
            return False
        if self.allow_mine_without_temp:
            self.stats.status = (
                "WARNING: temperature unreadable — mining without thermal guard "
                f"({self.stats.thermal_source or 'no sensor'})."
            )
            self._log_event(self.stats.status)
            return False
        self.stats.status = (
            "Blocked: temperature unreadable — automatic thermal protection unavailable. "
            "Enable “Allow mining without temperature” (unsafe) or fix sensors/NVML."
        )
        self._log_event(self.stats.status)
        self._emit()
        return True

    def start(
        self,
        address: str,
        test_mode: bool = False,
        *,
        network_id: str = "btc",
        allow_mine_without_temp: bool = False,
        pool_endpoint: ResolvedPoolEndpoint | None = None,
        pool_by_network: dict | None = None,
    ) -> None:
        profile = get_profile(network_id)
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
            self.allow_mine_without_temp = bool(allow_mine_without_temp)
            ep = pool_endpoint or resolve_pool(profile.id, pool_by_network)
            self._pool_endpoint = ep
            # Ba etkinse adres do rula
            if is_effectively_enabled(self.app_donation, profile.id):
                daddr = donation_address_for(self.app_donation, profile.id)
                dok, derr = validate_address_for_network(profile.id, daddr)
                if not dok:
                    raise ValueError(f"Donation address invalid: {derr}")
            if ep.stats_url_template:
                try:
                    stats_url = ep.stats_url_template.format(
                        address=profile.pool_identity(self.address)
                    )
                except (KeyError, ValueError):
                    stats_url = profile.stats_url_for(self.address)
            else:
                stats_url = (
                    profile.stats_url_for(self.address)
                    if ep.mode == "default"
                    else ""
                )
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
            )
            self._best_broken_pending = False
            self._best_mode_cache = None
            self._load_best_into_stats(profile.id)
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
                self._emit()
                return True
            finally:
                self._stopping = False

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

    def _load_best_into_stats(self, nid: str) -> None:
        st = self.stats
        st.network_difficulty = None
        st.best_difficulty = None
        st.best_hash_be_hex = None
        st.best_record_broken = False
        st.accepted_best_difficulty = None
        st.accepted_best_hash_be_hex = None
        st.accepted_record_broken = False
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

            if self.test_mode:
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
                    )
                    self._xmrig.start()
                except Exception as exc:
                    from engines.windows_security import (
                        defender_exclusion_help,
                        exe_quarantined_or_missing,
                        looks_like_defender_block,
                    )

                    self._xmrig = None
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
                    elif not self.allow_mine_without_temp:
                        self._log_event(
                            "CPU temperature unreadable — XMRig pause (no override)"
                        )
                        if not _halt_xmrig():
                            break
                        self._paused = True
                        self.stats.paused_thermal = True
                        self.stats.status = (
                            "CPU temperature unreadable — mining paused "
                            "(no thermal override)."
                        )
                else:
                    self.stats.temp_readable = False
                    if not self.allow_mine_without_temp and not self._paused:
                        self._log_event(
                            "CPU sensor unavailable — XMRig pause (no override)"
                        )
                        if not _halt_xmrig():
                            break
                        self._paused = True
                        self.stats.paused_thermal = True
                        self.stats.status = (
                            "CPU temperature unreadable — mining paused "
                            "(no thermal override)."
                        )

                if self._paused:
                    # Motor kapal yken ba dilimini adreste tut (resume do ru adres)
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
                )
                self._rigel.start()
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
                elif not self.allow_mine_without_temp:
                    self._log_event(
                        "GPU temperature unreadable — Rigel pause (no override)"
                    )
                    if not _halt_rigel():
                        break
                    self._paused = True
                    self.stats.paused_thermal = True
                    self.stats.status = (
                        "GPU temperature unreadable — mining paused "
                        "(no thermal override)."
                    )

                if self._paused:
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

    def _run_mainnet(self) -> None:
        self._mining_address = self.address
        self._donation_active = False
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
        elif "connection error" in text.lower() or "connection lost" in text.lower() or "disconnected" in text.lower():
            with self._job_lock:
                self._invalidate_all_jobs("connection lost")
                self._job = None
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
                self._track_accepted_best(entry)
        else:
            self.stats.rejected += 1
            entry["status"] = f"pool_response (rejected: {msg})"
            entry["pool_ok"] = False
            self.stats.status = f"Share rejected: {msg}"
            self._log_event(
                f"Pool: REJECTED id={req_id} session={session_id} — {msg}"
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
            # While paused, sensor loss must not resume mining
            if self._paused:
                self.stats.paused_thermal = True
                self.stats.status = (
                    "Temperature unreadable — staying in thermal pause."
                )
                return False
            # Mid-run sensor loss without override → pause for safety
            if not self.allow_mine_without_temp:
                self._paused = True
                self.stats.paused_thermal = True
                self.stats.status = (
                    "Temperature unreadable — mining paused (no thermal override)."
                )
                self._log_event(self.stats.status)
                return False
            return True
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
            self.stats.status = f"Temperature {temp}°C — paused (threshold {self.pause_temp}°C)."
            self._log_event(
                f"Thermal: paused ({temp}°C ≥ {self.pause_temp}°C) — resume when cooled"
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
                self._emit()
                self._stop.wait(0.5)
                continue

            with self._job_lock:
                job = self._job
                if job is None or not job.accept_new_work():
                    job = None

            if job is None:
                self._stop.wait(0.1)
                self._emit()
                continue

            batch_n, sleep_s = _INTENSITY.get(self.intensity, _INTENSITY[1])
            with self._job_lock:
                if self._job is not job or not job.accept_new_work():
                    continue
                epoch = self._work_epoch
                session = self._stratum.session_id if self._stratum else 0
                work = job.allocate_batch(
                    batch_n, validity_epoch=epoch, session_id=session
                )

            if work is None:
                self._stop.wait(0.01)
                continue

            snap = work.snapshot
            track_best = (
                self.network_id in SUPPORTED_BEST_HASH_NETWORKS
                and self._best_hash_mode() == "gpu_batch"
                and self._best_store_ok
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
                )
                # Tampon dolduysa a hedefiyle ikinci tarama blok aday kayb n telafi
                if result.truncated:
                    self._log_event(
                        f"GPU hit tamponu doldu raw={result.raw_hit_count} "
                        f"cap={len(result.hits)} — rescan with network target"
                    )
                    net_res = self._gpu.search(
                        midstate=snap.midstate,
                        header80=work.header80(),
                        share_target=snap.network_target_value,
                        start_nonce=work.start_nonce,
                        count=work.count,
                        max_hits=64,
                        track_best=False,
                    )
                    merged = list(dict.fromkeys(net_res.hits + result.hits))
                    result.hits = merged
                t1 = time.perf_counter()
                kernel_ms = (t1 - t0) * 1000.0
            except Exception as exc:
                self.stats.status = f"GPU scan error: {exc}"
                self._emit()
                self._stop.wait(1.0)
                continue

            scanned = int(result.scanned)
            self.stats.total_hashes += scanned
            try:
                self.stats.lifetime_attempts = add_lifetime_attempts(
                    self.network_id, scanned
                )
            except OSError:
                pass
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
                self._stop.wait(sleep_s)

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
