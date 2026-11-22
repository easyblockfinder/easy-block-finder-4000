"""XMRig process management + HTTP API (donate share separation)."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from app_meta import APP_USER_AGENT, XMRIG_HTTP_PORT, XMRIG_HTTP_TOKEN

log = logging.getLogger(__name__)

# E.g.: "new job from xmr.kryptex.network:7029 diff 100001 algo rx/0 height 3123456"
_NEW_JOB_RE = re.compile(
    r"new job from\s+\S+\s+diff\s+(\d+)(?:\s+algo\s+\S+)?(?:\s+height\s+(\d+))?",
    re.IGNORECASE,
)


@dataclass
class XmrigSnapshot:
    hashrate: float = 0.0
    accepted: int = 0
    rejected: int = 0
    engine_fee_shares: int = 0
    unattributed_shares: int = 0
    connected: bool = False
    pool: str = ""
    donating: bool = False
    status: str = ""
    generation: int = 0
    job_id: str = ""
    difficulty: Optional[float] = None
    # Process-session hashes from results.hashes_total (delta since last poll).
    hashes_total: int = 0
    hashes_delta: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


def parse_xmrig_new_job(line: str) -> tuple[Optional[int], Optional[int]]:
    """From the stdout line (diff, height) — if not (None, None)."""
    m = _NEW_JOB_RE.search(line or "")
    if not m:
        return None, None
    diff = int(m.group(1))
    height = int(m.group(2)) if m.group(2) else None
    return diff, height


def format_xmrig_job_label(
    *, height: Optional[int], diff: Optional[float], pool: str = ""
) -> str:
    parts: list[str] = []
    if height is not None and height > 0:
        parts.append(f"height={height}")
    if diff is not None and diff > 0:
        parts.append(f"diff={int(diff)}" if float(diff).is_integer() else f"diff={diff}")
    if not parts and pool:
        parts.append(f"pool={pool}")
    return " · ".join(parts)


class XmrigRunner:
    def __init__(
        self,
        exe: Path,
        *,
        host: str,
        port: int,
        username: str,
        password: str = "x",
        donate_level: int = 1,
        threads: int = 0,
        http_port: int = 40789,
        http_token: str = "",
        on_snapshot: Optional[Callable[[XmrigSnapshot], None]] = None,
        user_pool_hint: str = "kryptex",
        generation: int = 0,
        use_tls: bool = False,
    ) -> None:
        self.exe = Path(exe)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.donate_level = max(0, int(donate_level))
        self.threads = int(threads)
        self.http_port = int(http_port or XMRIG_HTTP_PORT)
        self.http_token = http_token or XMRIG_HTTP_TOKEN
        self.on_snapshot = on_snapshot
        self.user_pool_hint = user_pool_hint.lower()
        self.generation = int(generation)
        self.use_tls = bool(use_tls)
        self._retired = False

        self._proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._poller: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        # HTTP response order: the old response is rejected with the ticket (poll∥refresh race)
        self._api_ticket = 0
        self._api_applied = 0
        self._last_good = 0
        self._last_total = 0
        self._last_pool_kind: Optional[str] = None
        self._user_accepted = 0
        self._user_rejected = 0
        self._fee_shares = 0
        self._unattributed = 0
        self._job_height: Optional[int] = None
        self._job_diff: Optional[float] = None
        self._last_hashes_raw: Optional[int] = None
        self._hashes_session = 0
        self.recent_log: list[str] = []
        self.snapshot = XmrigSnapshot(generation=self.generation)

    def start(self) -> None:
        if self._proc and self._proc.poll() is None:
            raise RuntimeError("XMRig is already running.")
        # Application xmrig remaining from the previous session (same HTTP port / token)
        try:
            from engines.orphan_miners import kill_app_xmrig

            n, failed = kill_app_xmrig()
            if n:
                log.warning("%s orphan processes cleared before XMRig start", n)
            if failed:
                raise RuntimeError(
                    f"Previous XMRig did not exit (pid={failed}); cannot open new session."
                )
        except RuntimeError:
            raise
        except Exception:
            log.exception("yetim XMRig tarama")
        url = f"{self.host}:{self.port}"
        cmd = [
            str(self.exe),
            f"--url={url}",
            f"--user={self.username}",
            f"--pass={self.password}",
            "--algo=rx/0",
            f"--donate-level={self.donate_level}",
            f"--http-host=127.0.0.1",
            f"--http-port={self.http_port}",
            f"--http-access-token={self.http_token}",
            "--http-no-restricted",
            "--no-color",
        ]
        if self.use_tls:
            cmd.append("--tls")
        if self.threads > 0:
            cmd.append(f"--threads={self.threads}")

        creation = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

        self._stop.clear()
        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(self.exe.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation,
            )
        except OSError as exc:
            from engines.windows_security import (
                defender_exclusion_help,
                exe_quarantined_or_missing,
                looks_like_defender_block,
            )

            if looks_like_defender_block(exc) or exe_quarantined_or_missing(self.exe):
                raise RuntimeError(defender_exclusion_help("XMRig")) from exc
            raise
        threading.Thread(target=self._drain_stdout, name="xmrig-log", daemon=True).start()
        self._poller = threading.Thread(target=self._poll_loop, name="xmrig-poll", daemon=True)
        self._poller.start()

    def _drain_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                if self._stop.is_set():
                    break
                text = (line or "").rstrip()
                if not text:
                    continue
                self.recent_log.append(text)
                if len(self.recent_log) > 40:
                    self.recent_log = self.recent_log[-40:]
                self._note_job_from_log(text)
        except Exception:
            log.exception("XMRig stdout")

    def _note_job_from_log(self, line: str) -> None:
        diff, height = parse_xmrig_new_job(line)
        if diff is None and height is None:
            return
        with self._lock:
            if self._retired:
                return
            if diff is not None:
                self._job_diff = float(diff)
            if height is not None:
                self._job_height = height
            pool = self.snapshot.pool
            label = format_xmrig_job_label(
                height=self._job_height, diff=self._job_diff, pool=pool
            )
            self.snapshot.job_id = label
            if self._job_diff is not None:
                self.snapshot.difficulty = self._job_diff
            self.snapshot.status = f"XMRig new job: {label}" if label else self.snapshot.status
            snap = XmrigSnapshot(
                hashrate=self.snapshot.hashrate,
                accepted=self.snapshot.accepted,
                rejected=self.snapshot.rejected,
                engine_fee_shares=self.snapshot.engine_fee_shares,
                unattributed_shares=self.snapshot.unattributed_shares,
                connected=self.snapshot.connected,
                pool=self.snapshot.pool,
                donating=self.snapshot.donating,
                status=self.snapshot.status,
                generation=self.generation,
                job_id=self.snapshot.job_id,
                difficulty=self.snapshot.difficulty,
                raw=dict(self.snapshot.raw) if self.snapshot.raw else {},
            )
            cb = self.on_snapshot
        if cb is not None:
            try:
                cb(snap)
            except Exception:
                log.exception("xmrig on_snapshot (job log)")

    def _begin_api_request(self) -> Optional[int]:
        with self._lock:
            if self._retired:
                return None
            self._api_ticket += 1
            return self._api_ticket

    def apply_api_result(self, ticket: int, summary: dict[str, Any]) -> bool:
        """
        Ticket ordering: stale tickets rejected after a newer response is applied.
        Counter updates share the ticket lock (out-of-order HTTP safe).
        """
        return self._ingest(summary, api_ticket=ticket)

    def _poll_once(self) -> None:
        ticket = self._begin_api_request()
        if ticket is None:
            return
        try:
            summary = self._api_get("/2/summary")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            with self._lock:
                if self._retired or ticket <= self._api_applied:
                    return
                # Errors also consume tickets — don't let delayed old success resets/over-counts occur
                self._api_applied = ticket
                self.snapshot.status = f"XMRig API bekleniyor: {exc}"
                if self._proc and self._proc.poll() is not None:
                    self.snapshot.status = (
                        f"XMRig exited (code={self._proc.returncode})"
                    )
                    self.snapshot.connected = False
                snap = self.snapshot
                cb = self.on_snapshot
                proc_dead = self._proc is not None and self._proc.poll() is not None
            if cb is not None:
                try:
                    cb(snap)
                except Exception:
                    log.exception("xmrig on_snapshot")
            if proc_dead:
                self._stop.set()
            return
        self.apply_api_result(ticket, summary)

    def refresh_snapshot(self) -> None:
        """One last API read before retiring (reduces fold under-count)."""
        try:
            self._poll_once()
        except Exception:
            log.debug("XMRig refresh_snapshot failed", exc_info=True)

    def retire(self) -> None:
        """Disable callback; prevent pollers from sending delayed snapshots."""
        with self._lock:
            self._retired = True
            self.on_snapshot = None

    def take_final_snapshot(self) -> XmrigSnapshot:
        with self._lock:
            snap = self.snapshot
            return XmrigSnapshot(
                hashrate=snap.hashrate,
                accepted=snap.accepted,
                rejected=snap.rejected,
                engine_fee_shares=snap.engine_fee_shares,
                unattributed_shares=snap.unattributed_shares,
                connected=snap.connected,
                pool=snap.pool,
                donating=snap.donating,
                status=snap.status,
                generation=self.generation,
                job_id=snap.job_id,
                difficulty=snap.difficulty,
                raw=dict(snap.raw) if snap.raw else {},
            )

    def stop(self, timeout_s: float = 8.0) -> bool:
        """True = process terminated. False/Raise = still alive; _proc is preserved."""
        self.retire()
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                log.exception("XMRig terminate")
            try:
                proc.wait(timeout=timeout_s)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    log.exception("XMRig kill")
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
        if proc is not None and proc.poll() is None:
            # Process is active — cannot delete reference
            raise RuntimeError(
                "XMRig process did not exit (still alive after terminate/kill)."
            )
        self._proc = None
        poller = self._poller
        if poller is not None and poller.is_alive():
            poller.join(timeout=3)
            if poller.is_alive():
                log.warning(
                    "XMRig poller join timeout — referans korunuyor (gen=%s)",
                    self.generation,
                )
                return True
        self._poller = None
        return True

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def pause_mining(self) -> bool:
        """HTTP pause — keeps process/pool; localhost + token only."""
        from engines.xmrig_control import pause_xmrig

        return pause_xmrig(http_port=self.http_port, http_token=self.http_token)

    def resume_mining(self) -> bool:
        from engines.xmrig_control import resume_xmrig

        return resume_xmrig(http_port=self.http_port, http_token=self.http_token)

    def _api_get(self, path: str) -> dict[str, Any]:
        url = f"http://127.0.0.1:{self.http_port}{path}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.http_token}",
                "User-Agent": APP_USER_AGENT,
            },
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def _classify_pool(self, pool: str) -> str:
        """user | fee | unattributed — A user who cannot be proven is not recorded as accepted."""
        p = (pool or "").lower().strip()
        markers = ("donate", "fee", "xmrig.com", "c3pool.com", "supportxmr")
        if any(m in p for m in markers):
            return "fee"
        if not p:
            return "unattributed"
        if self.user_pool_hint and self.user_pool_hint in p:
            return "user"
        host = (self.host or "").lower()
        if host and host in p:
            return "user"
        expected = f"{host}:{int(self.port)}".lower() if host else ""
        if expected and expected in p:
            return "user"
        return "unattributed"

    def _is_donate_pool(self, pool: str) -> bool:
        return self._classify_pool(pool) == "fee"

    def _poll_loop(self) -> None:
        # Let the API get up and running
        time.sleep(2.0)
        while not self._stop.is_set():
            self._poll_once()
            if self._stop.is_set():
                break
            self._stop.wait(2.0)

    def _ingest(
        self, summary: dict[str, Any], *, api_ticket: Optional[int] = None
    ) -> bool:
        """
        XMRig /2/summary: results.shares_* are process-wide cumulative (not per-pool).
        Delta across connect/donate switches cannot be classified -> unattributed.
        When api_ticket is set, stale responses are rejected (poll parallel refresh).
        """
        conn = summary.get("connection") or {}
        pool = str(conn.get("pool") or conn.get("ip") or "")
        results = summary.get("results") or {}
        good = int(results.get("shares_good") or 0)
        total = int(results.get("shares_total") or 0)
        try:
            hashes_raw = int(results.get("hashes_total") or 0)
        except (TypeError, ValueError):
            hashes_raw = 0
        if hashes_raw < 0:
            hashes_raw = 0
        hash_obj = summary.get("hashrate") or {}
        total_hr = hash_obj.get("total") or [0]
        hr = float(total_hr[0] or 0) if isinstance(total_hr, list) else float(total_hr or 0)
        api_diff_raw = conn.get("diff")
        if api_diff_raw is None:
            api_diff_raw = results.get("diff_current")
        api_diff: Optional[float] = None
        try:
            if api_diff_raw is not None:
                api_diff = float(api_diff_raw)
        except (TypeError, ValueError):
            api_diff = None

        kind = self._classify_pool(pool)
        donating = kind == "fee"
        with self._lock:
            if self._retired:
                return False
            if api_ticket is not None:
                if api_ticket <= self._api_applied:
                    return False
                self._api_applied = api_ticket
            # Counter reset / reconnected
            if good < self._last_good or total < self._last_total:
                self._last_good = good
                self._last_total = total
                self._last_pool_kind = kind
                d_good = 0
                d_rej = 0
            else:
                d_good = max(0, good - self._last_good)
                d_total = max(0, total - self._last_total)
                d_rej = max(0, d_total - d_good)
            prev = self._last_pool_kind
            if d_good:
                # Switch interval or pool change after the first sample → unattributed
                if prev is not None and prev != kind:
                    self._unattributed += d_good
                    assign = "unattributed"
                elif kind == "fee":
                    self._fee_shares += d_good
                    assign = "fee"
                elif kind == "user":
                    self._user_accepted += d_good
                    assign = "user"
                else:
                    self._unattributed += d_good
                    assign = "unattributed"
            else:
                assign = kind
            if d_rej:
                if prev is not None and prev != kind:
                    pass  # unspecified reject — user rejected inflation
                elif kind == "user":
                    self._user_rejected += d_rej
            self._last_good = good
            self._last_total = total
            self._last_pool_kind = kind
            # hashes_total is process-wide (includes donate); first sample is baseline.
            hashes_delta = 0
            if self._last_hashes_raw is None:
                self._last_hashes_raw = hashes_raw
            elif hashes_raw < self._last_hashes_raw:
                self._last_hashes_raw = hashes_raw
            else:
                hashes_delta = hashes_raw - self._last_hashes_raw
                self._last_hashes_raw = hashes_raw
                self._hashes_session += hashes_delta
            if assign == "fee" or kind == "fee":
                status = (
                    f"XMRig donate period (fee share, not user accepted) pool={pool}"
                )
            elif assign == "unattributed" or kind == "unattributed":
                status = (
                    f"XMRig unattributed share (+{self._unattributed}) pool={pool!r}"
                )
            else:
                status = f"XMRig connected pool={pool}"
            if api_diff is not None and api_diff > 0:
                self._job_diff = api_diff
            job_label = format_xmrig_job_label(
                height=self._job_height, diff=self._job_diff, pool=pool
            )
            self.snapshot = XmrigSnapshot(
                hashrate=hr,
                accepted=self._user_accepted,
                rejected=self._user_rejected,
                engine_fee_shares=self._fee_shares,
                unattributed_shares=self._unattributed,
                connected=bool(conn.get("uptime") or pool),
                pool=pool,
                donating=donating,
                status=status,
                generation=self.generation,
                job_id=job_label,
                difficulty=self._job_diff,
                hashes_total=self._hashes_session,
                hashes_delta=hashes_delta,
                raw=summary,
            )
            snap = self.snapshot
            cb = self.on_snapshot
        if cb is not None:
            try:
                cb(snap)
            except Exception:
                log.exception("xmrig on_snapshot")
        return True
