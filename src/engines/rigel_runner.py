"""Rigel process + HTTP API (devfee share separation)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class RigelSnapshot:
    hashrate: float = 0.0
    accepted: int = 0
    rejected: int = 0
    engine_fee_shares: int = 0
    unattributed_shares: int = 0
    connected: bool = False
    pool: str = ""
    fee_period: bool = False
    status: str = ""
    generation: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class RigelRunner:
    def __init__(
        self,
        exe: Path,
        *,
        algorithm: str,
        coin: str,
        host: str,
        port: int,
        username: str,
        password: str = "x",
        device_index: int = 0,
        api_port: int = 5001,
        on_snapshot: Optional[Callable[[RigelSnapshot], None]] = None,
        user_pool_hint: str = "2miners",
        env_extra: Optional[dict[str, str]] = None,
        log_lines: int = 40,
        generation: int = 0,
        use_tls: bool = False,
    ) -> None:
        self.exe = Path(exe)
        self.algorithm = algorithm
        self.coin = coin
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.device_index = int(device_index)
        self.api_port = int(api_port)
        self.on_snapshot = on_snapshot
        self.user_pool_hint = user_pool_hint.lower()
        self.env_extra = dict(env_extra or {})
        self.log_lines = max(0, int(log_lines))
        self.generation = int(generation)
        self.use_tls = bool(use_tls)
        self._retired = False

        self._proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._poller: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._api_ticket = 0
        self._api_applied = 0
        self._last_acc = 0
        self._last_rej = 0
        self._last_pool_kind: Optional[str] = None
        self._user_accepted = 0
        self._user_rejected = 0
        self._fee_shares = 0
        self._unattributed = 0
        self.recent_log: list[str] = []
        self.snapshot = RigelSnapshot(generation=self.generation)

    def start(self) -> None:
        if self._proc and self._proc.poll() is None:
            raise RuntimeError("Rigel is already running.")
        scheme = "stratum+ssl" if self.use_tls else "stratum+tcp"
        pool = f"{scheme}://{self.host}:{self.port}"
        cmd = [
            str(self.exe),
            "-a",
            self.algorithm,
            "--coin",
            self.coin,
            "-o",
            pool,
            "-u",
            self.username,
            "-p",
            self.password,
            "-d",
            str(self.device_index),
            "--api-bind",
            f"127.0.0.1:{self.api_port}",
            "--no-colour",
        ]
        creation = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        env = _rigel_child_env(self.env_extra)
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
                env=env,
                creationflags=creation,
            )
        except OSError as exc:
            from engines.windows_security import (
                defender_exclusion_help,
                exe_quarantined_or_missing,
                looks_like_defender_block,
            )

            if looks_like_defender_block(exc) or exe_quarantined_or_missing(self.exe):
                raise RuntimeError(defender_exclusion_help("Rigel")) from exc
            raise
        if self.log_lines > 0:
            threading.Thread(
                target=self._drain_stdout, name="rigel-log", daemon=True
            ).start()
        self._poller = threading.Thread(target=self._poll_loop, name="rigel-poll", daemon=True)
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
                if len(self.recent_log) > self.log_lines:
                    self.recent_log = self.recent_log[-self.log_lines :]
        except Exception:
            log.exception("Rigel stdout")

    def _begin_api_request(self) -> Optional[int]:
        with self._lock:
            if self._retired:
                return None
            self._api_ticket += 1
            return self._api_ticket

    def apply_api_result(self, ticket: int, data: dict[str, Any]) -> bool:
        return self._ingest(data, api_ticket=ticket)

    def _poll_once(self) -> None:
        ticket = self._begin_api_request()
        if ticket is None:
            return
        try:
            data = self._api_get()
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            with self._lock:
                if self._retired or ticket <= self._api_applied:
                    return
                self._api_applied = ticket
                self.snapshot.status = f"Rigel API bekleniyor: {exc}"
                proc_dead = self._proc is not None and self._proc.poll() is not None
                if proc_dead:
                    self.snapshot.status = (
                        f"Rigel exited (code={self._proc.returncode})"
                    )
                    self.snapshot.connected = False
                snap = self.snapshot
                cb = self.on_snapshot
            if cb is not None:
                try:
                    cb(snap)
                except Exception:
                    log.exception("rigel on_snapshot")
            if proc_dead:
                self._stop.set()
            return
        self.apply_api_result(ticket, data)

    def refresh_snapshot(self) -> None:
        """One last API read before retiring (reduces fold under-count)."""
        try:
            self._poll_once()
        except Exception:
            log.debug("Rigel refresh_snapshot failed", exc_info=True)

    def retire(self) -> None:
        with self._lock:
            self._retired = True
            self.on_snapshot = None

    def take_final_snapshot(self) -> RigelSnapshot:
        with self._lock:
            snap = self.snapshot
            return RigelSnapshot(
                hashrate=snap.hashrate,
                accepted=snap.accepted,
                rejected=snap.rejected,
                engine_fee_shares=snap.engine_fee_shares,
                unattributed_shares=snap.unattributed_shares,
                connected=snap.connected,
                pool=snap.pool,
                fee_period=snap.fee_period,
                status=snap.status,
                generation=self.generation,
                raw=dict(snap.raw) if snap.raw else {},
            )

    def stop(self, timeout_s: float = 8.0) -> bool:
        """True = process terminated. Raise = still alive; _proc is preserved."""
        self.retire()
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                log.exception("Rigel terminate")
            try:
                proc.wait(timeout=timeout_s)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    log.exception("Rigel kill")
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
        if proc is not None and proc.poll() is None:
            raise RuntimeError(
                "Rigel process did not exit (still alive after terminate/kill)."
            )
        self._proc = None
        poller = self._poller
        if poller is not None and poller.is_alive():
            poller.join(timeout=3)
            if poller.is_alive():
                log.warning(
                    "Rigel poller join timeout — referans korunuyor (gen=%s)",
                    self.generation,
                )
                return True
        self._poller = None
        return True

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _api_get(self) -> dict[str, Any]:
        url = f"http://127.0.0.1:{self.api_port}/"
        from app_meta import APP_USER_AGENT

        req = urllib.request.Request(url, headers={"User-Agent": APP_USER_AGENT})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def _classify_pool(self, pool: str) -> str:
        """user | fee | unattributed"""
        p = (pool or "").lower().strip()
        if not p:
            return "unattributed"
        if self.user_pool_hint and self.user_pool_hint in p:
            return "user"
        host = (self.host or "").lower()
        if host and host in p:
            return "user"
        markers = ("fee", "devfee", "rigel")
        if any(m in p for m in markers):
            return "fee"
        return "unattributed"

    def _is_fee_pool(self, pool: str) -> bool:
        return self._classify_pool(pool) != "user"

    def _poll_loop(self) -> None:
        time.sleep(3.0)
        while not self._stop.is_set():
            self._poll_once()
            if self._stop.is_set():
                break
            self._stop.wait(2.0)

    def _ingest(
        self, data: dict[str, Any], *, api_ticket: Optional[int] = None
    ) -> bool:
        # Flexible field reading (Rigel versions may vary)
        hr = 0.0
        if "hr_total" in data:
            hr = float(data.get("hr_total") or 0)
        elif "hashrate" in data:
            h = data["hashrate"]
            if isinstance(h, dict):
                hr = float((h.get("total") or [0])[0] if isinstance(h.get("total"), list) else h.get("total") or 0)
            else:
                hr = float(h or 0)
        elif isinstance(data.get("algorithms"), list) and data["algorithms"]:
            algo0 = data["algorithms"][0] or {}
            hr = float(algo0.get("hashrate") or algo0.get("hr") or 0)

        shares = data.get("shares") or data.get("solution_stats") or {}
        if isinstance(data.get("algorithms"), list) and data["algorithms"]:
            algo0 = data["algorithms"][0] or {}
            if not shares:
                shares = algo0.get("shares") or {}
        acc = int(shares.get("accepted") or shares.get("valid") or 0)
        rej = int(shares.get("rejected") or shares.get("invalid") or 0)

        pool = ""
        for key in ("pool", "url", "connection"):
            if key in data and data[key]:
                pool = str(data[key])
                break
        if not pool and isinstance(data.get("algorithms"), list) and data["algorithms"]:
            pool = str((data["algorithms"][0] or {}).get("pool") or "")

        kind = self._classify_pool(pool)
        with self._lock:
            if self._retired:
                return False
            if api_ticket is not None:
                if api_ticket <= self._api_applied:
                    return False
                self._api_applied = api_ticket
            if acc < self._last_acc or rej < self._last_rej:
                self._last_acc = acc
                self._last_rej = rej
                self._last_pool_kind = kind
                d_acc = 0
                d_rej = 0
            else:
                d_acc = max(0, acc - self._last_acc)
                d_rej = max(0, rej - self._last_rej)
            prev = self._last_pool_kind
            if d_acc:
                if prev is not None and prev != kind:
                    self._unattributed += d_acc
                    assign = "unattributed"
                elif kind == "user":
                    self._user_accepted += d_acc
                    assign = "user"
                elif kind == "fee":
                    self._fee_shares += d_acc
                    assign = "fee"
                else:
                    self._unattributed += d_acc
                    assign = "unattributed"
            else:
                assign = kind
            if d_rej and (prev is None or prev == kind) and kind == "user":
                self._user_rejected += d_rej
            self._last_acc = acc
            self._last_rej = rej
            self._last_pool_kind = kind
            self.snapshot = RigelSnapshot(
                hashrate=hr,
                accepted=self._user_accepted,
                rejected=self._user_rejected,
                engine_fee_shares=self._fee_shares,
                unattributed_shares=self._unattributed,
                connected=True,
                pool=pool,
                fee_period=kind == "fee",
                status=(
                    f"Rigel fee period (not user accepted) pool={pool}"
                    if assign == "fee" or kind == "fee"
                    else (
                        f"Rigel unattributed share (+{self._unattributed}) pool={pool!r}"
                        if assign == "unattributed" or kind == "unattributed"
                        else f"Rigel connected pool={pool or self.host}"
                    )
                ),
                generation=self.generation,
                raw=data,
            )
            snap = self.snapshot
            cb = self.on_snapshot
        if cb is not None:
            try:
                cb(snap)
            except Exception:
                log.exception("rigel on_snapshot")
        return True


def _rigel_child_env(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Copy the main environment; clear filters such as CUDA_VISIBLE_DEVICES."""
    env = os.environ.copy()
    for key in (
        "CUDA_VISIBLE_DEVICES",
        "HIP_VISIBLE_DEVICES",
        "ROCR_VISIBLE_DEVICES",
        "GPU_DEVICE_ORDINAL",
    ):
        env.pop(key, None)
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    if extra:
        env.update(extra)
    # Empty CUDA_VISIBLE_DEVICES can hide all devices — delete
    if not (env.get("CUDA_VISIBLE_DEVICES") or "").strip():
        env.pop("CUDA_VISIBLE_DEVICES", None)
    return env


def _bus_key(bus_id: str) -> str:
    """domain:bus:device:function — the domain is not omitted (so that different devices are not mistaken for the same device)."""
    hexes = re.findall(r"[0-9A-Fa-f]+", (bus_id or "").upper())
    if not hexes:
        return ""
    # 00000000:01:00.0 → 4 parts; 0000:01:00.0 → 4
    norms = [format(int(h, 16), "x") for h in hexes]
    if len(norms) >= 4:
        return ":".join(norms[-4:])
    if len(norms) == 3:
        # domain missing → ambiguous; the caller should return an error in the match
        return "?:%s" % (":".join(norms))
    return ":".join(norms)


def parse_rigel_list_devices(text: str) -> list[dict[str, Any]]:
    """GPU index + bus from the Rigel --list-devices output."""
    devices: list[dict[str, Any]] = []
    for m in re.finditer(
        r"GPU\s+#(\d+)\s+\[([0-9A-Fa-f:.]+)\]",
        text or "",
        flags=re.IGNORECASE,
    ):
        devices.append(
            {
                "index": int(m.group(1)),
                "bus_id": m.group(2),
            }
        )
    return devices


def resolve_rigel_device_index(
    *,
    selected_bus: str,
    selected_uuid: str = "",
    rigel_devices: list[dict[str, Any]],
    nvml_devices: Any = None,
) -> int:
    """
    Map selected PCI bus to index in Rigel's live device list.
    No silent fallback on mismatch — RuntimeError.
    nvml_devices is for tests/docs only; mapping follows Rigel's list.
    """
    del nvml_devices  # API compatibility; NVML sequence not used
    want = _bus_key(selected_bus)
    if not want or want.startswith("?"):
        raise RuntimeError(
            f"Selected GPU bus ID ambiguous/missing domain (bus={selected_bus}) — "
            "Cannot map Rigel device."
        )
    matches = [
        d
        for d in rigel_devices
        if _bus_key(str(d.get("bus_id") or "")) == want
    ]
    if len(matches) > 1:
        raise RuntimeError(
            f"Ambiguous Rigel PCI mapping: bus={selected_bus} → {len(matches)} devices."
        )
    if len(matches) == 1:
        return int(matches[0]["index"])
    raise RuntimeError(
        f"No match in Rigel --list-devices (bus={selected_bus} uuid={selected_uuid}). "
        "CUDA_VISIBLE_DEVICES / order mismatch possible; will not fall back to another GPU."
    )


def probe_rigel_devices(exe: Path, timeout_s: float = 45.0) -> list[dict[str, Any]]:
    """Run Rigel --list-devices; CUDA_VISIBLE_DEVICES is clear in the child environment."""
    creation = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    env = _rigel_child_env()
    try:
        proc = subprocess.run(
            [str(exe), "--list-devices"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            cwd=str(Path(exe).parent),
            env=env,
            creationflags=creation,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Rigel --list-devices timeout: {exc}") from exc
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    devices = parse_rigel_list_devices(text)
    # Exit code required: some versions write the list to stderr and return 0; non-0 = error
    if proc.returncode not in (0, None):
        raise RuntimeError(
            f"Rigel --list-devices exit={proc.returncode} (failed). "
            f"output={text[:400]!r}"
        )
    if not devices:
        raise RuntimeError(
            "Rigel --list-devices returned no devices / could not verify. "
            f"exit={proc.returncode} output={text[:400]!r}"
        )
    return devices
