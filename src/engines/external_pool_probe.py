"""Brief external-miner pool probe — auth + job required; always tear down."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from networks.pool_connection_test import PoolConnectionTestResult
from networks.pool_input import sanitize_host, parse_port, validate_password
from networks.pool_types import Transport


@dataclass
class _ProbeState:
    got_job: bool = False
    connected: bool = False
    detail: str = ""


def probe_xmrig_pool(
    *,
    exe: Path,
    host: str,
    port: int,
    username: str,
    password: str = "x",
    transport: Transport = "tcp",
    timeout_s: float = 35.0,
    http_port: int = 41789,
    threads: int = 1,
) -> PoolConnectionTestResult:
    from engines.xmrig_runner import XmrigRunner

    clean_host = sanitize_host(host)
    clean_port = parse_port(port)
    clean_pass = validate_password(password)
    user = (username or "").strip()
    if not user:
        return PoolConnectionTestResult(
            ok=False,
            stage="failed",
            message="Authorize username required for XMRig pool test.",
            host=clean_host,
            port=clean_port,
        )

    state = _ProbeState()

    def on_snap(snap) -> None:
        if getattr(snap, "connected", False):
            state.connected = True
        job = str(getattr(snap, "job_id", "") or "").strip()
        if job:
            state.got_job = True
            state.detail = job
        status = str(getattr(snap, "status", "") or "")
        if "new job" in status.lower():
            state.got_job = True
            state.detail = status

    runner = XmrigRunner(
        Path(exe),
        host=clean_host,
        port=clean_port,
        username=user,
        password=clean_pass,
        donate_level=1,
        threads=max(1, int(threads)),
        http_port=int(http_port),
        on_snapshot=on_snap,
        user_pool_hint="probe",
        generation=0,
        use_tls=(transport == "tls"),
    )
    try:
        runner.start()
        deadline = time.monotonic() + max(8.0, float(timeout_s))
        while time.monotonic() < deadline:
            if state.got_job:
                break
            for line in list(runner.recent_log):
                low = line.lower()
                if "new job" in low:
                    state.got_job = True
                    state.detail = line.strip()
                    break
                if "authorized" in low or "login" in low:
                    state.connected = True
            if state.got_job:
                break
            time.sleep(0.2)
        if state.got_job:
            return PoolConnectionTestResult(
                ok=True,
                stage="job",
                message=(
                    f"OK — XMRig authorized and received a job from "
                    f"{clean_host}:{clean_port} ({state.detail[:120]})."
                ),
                host=clean_host,
                port=clean_port,
                job_id=state.detail[:80],
                authorized=True,
            )
        if state.connected:
            return PoolConnectionTestResult(
                ok=False,
                stage="authorized",
                message=(
                    "XMRig connected/authorized but no job was observed in time. "
                    "Connection alone is not a successful pool test."
                ),
                host=clean_host,
                port=clean_port,
                authorized=True,
            )
        return PoolConnectionTestResult(
            ok=False,
            stage="failed",
            message="XMRig did not obtain a pool job before timeout.",
            host=clean_host,
            port=clean_port,
        )
    except Exception as exc:
        return PoolConnectionTestResult(
            ok=False,
            stage="failed",
            message=f"XMRig pool test error: {exc}",
            host=clean_host,
            port=clean_port,
        )
    finally:
        try:
            runner.stop(timeout_s=6.0)
        except Exception:
            pass
        try:
            from engines.orphan_miners import kill_app_xmrig

            kill_app_xmrig()
        except Exception:
            pass


def probe_rigel_pool(
    *,
    exe: Path,
    algorithm: str,
    coin: str,
    host: str,
    port: int,
    username: str,
    password: str = "x",
    transport: Transport = "tcp",
    timeout_s: float = 45.0,
    api_port: int = 5101,
    device_index: int = 0,
) -> PoolConnectionTestResult:
    from engines.rigel_runner import RigelRunner

    clean_host = sanitize_host(host)
    clean_port = parse_port(port)
    clean_pass = validate_password(password)
    user = (username or "").strip()
    if not user:
        return PoolConnectionTestResult(
            ok=False,
            stage="failed",
            message="Authorize username required for Rigel pool test.",
            host=clean_host,
            port=clean_port,
        )

    state = _ProbeState()

    def on_snap(snap) -> None:
        if getattr(snap, "connected", False) and getattr(snap, "pool", ""):
            state.connected = True
            # API-connected with pool usually means work is live; still prefer job log.
            state.detail = str(getattr(snap, "pool", "") or "")

    runner = RigelRunner(
        Path(exe),
        algorithm=algorithm,
        coin=coin,
        host=clean_host,
        port=clean_port,
        username=user,
        password=clean_pass,
        device_index=int(device_index),
        api_port=int(api_port),
        on_snapshot=on_snap,
        user_pool_hint="probe",
        env_extra={"CUDA_DEVICE_ORDER": "PCI_BUS_ID"},
        generation=0,
        use_tls=(transport == "tls"),
    )
    try:
        runner.start()
        deadline = time.monotonic() + max(10.0, float(timeout_s))
        while time.monotonic() < deadline:
            for line in list(runner.recent_log):
                low = line.lower()
                if "job" in low or "epoch" in low or "dag" in low:
                    # DAG build precedes job; wait for clearer job/share/pool accept.
                    pass
                if "new job" in low or "received job" in low or "got job" in low:
                    state.got_job = True
                    state.detail = line.strip()
                if "authorized" in low or "logged in" in low or "login" in low:
                    state.connected = True
            if state.connected and (
                state.got_job
                or any("job" in (x or "").lower() for x in runner.recent_log[-15:])
            ):
                state.got_job = True
                break
            if state.got_job:
                break
            time.sleep(0.25)
        if state.got_job:
            return PoolConnectionTestResult(
                ok=True,
                stage="job",
                message=(
                    f"OK — Rigel authorized and observed pool work from "
                    f"{clean_host}:{clean_port}."
                ),
                host=clean_host,
                port=clean_port,
                job_id=state.detail[:80],
                authorized=True,
            )
        if state.connected:
            return PoolConnectionTestResult(
                ok=False,
                stage="authorized",
                message=(
                    "Rigel reached the pool API/connection, but a clear job was not "
                    "observed in time. Connection alone is not enough."
                ),
                host=clean_host,
                port=clean_port,
                authorized=True,
            )
        return PoolConnectionTestResult(
            ok=False,
            stage="failed",
            message="Rigel did not obtain pool work before timeout (GPU/DAG may be required).",
            host=clean_host,
            port=clean_port,
        )
    except Exception as exc:
        return PoolConnectionTestResult(
            ok=False,
            stage="failed",
            message=f"Rigel pool test error: {exc}",
            host=clean_host,
            port=clean_port,
        )
    finally:
        try:
            runner.stop(timeout_s=8.0)
        except Exception:
            pass
        try:
            from engines.orphan_miners import kill_app_rigel

            kill_app_rigel()
        except Exception:
            pass
