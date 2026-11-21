"""Native pool connection probe — success requires a real mining.notify/job.

TCP connect, subscribe, authorize, or set_difficulty alone is NOT success.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from networks.pool_input import mask_secret, sanitize_host, parse_port, validate_password
from networks.pool_types import Transport
from stratum.client import StratumClient


@dataclass(frozen=True)
class PoolConnectionTestResult:
    ok: bool
    stage: str  # failed | connected | authorized | job
    message: str
    host: str = ""
    port: int = 0
    job_id: str = ""
    difficulty: Optional[float] = None
    authorized: bool = False


def probe_native_pool_connection(
    *,
    host: str,
    port: int,
    username: str,
    password: str = "x",
    transport: Transport = "tcp",
    timeout_s: float = 25.0,
) -> PoolConnectionTestResult:
    """
    Brief live handshake. Always stops the temporary StratumClient afterwards.
    """
    try:
        clean_host = sanitize_host(host)
        clean_port = parse_port(port)
        clean_pass = validate_password(password)
    except ValueError as exc:
        return PoolConnectionTestResult(
            ok=False, stage="failed", message=str(exc), host=host, port=int(port or 0)
        )

    user = (username or "").strip()
    if not user:
        return PoolConnectionTestResult(
            ok=False,
            stage="failed",
            message="A payout / authorize username is required for the connection test.",
            host=clean_host,
            port=clean_port,
        )

    if transport == "tls":
        return PoolConnectionTestResult(
            ok=False,
            stage="failed",
            message=(
                "TLS is not enabled yet (certificate verification required). "
                "Use a TCP pool for now."
            ),
            host=clean_host,
            port=clean_port,
        )

    got_job = threading.Event()
    job_id = ""
    stages = {"connected": False, "authorized": False}
    status_notes: list[str] = []
    client_holder: dict[str, Optional[StratumClient]] = {"c": None}

    def on_job(params: list, _clean: bool) -> None:
        nonlocal job_id
        if not params:
            return
        job_id = str(params[0] or "")
        if job_id:
            got_job.set()

    def on_status(text: str) -> None:
        status_notes.append(text)
        low = (text or "").lower()
        if "tcp connected" in low:
            stages["connected"] = True
        if "authorized" in low:
            stages["authorized"] = True

    client = StratumClient(
        host=clean_host,
        port=clean_port,
        on_job=on_job,
        on_status=on_status,
        suggest_difficulty=1.0,
        password=clean_pass,
    )
    client_holder["c"] = client
    deadline = time.monotonic() + max(5.0, float(timeout_s))
    try:
        client.start(user)
        while time.monotonic() < deadline:
            if got_job.is_set():
                break
            if client.authorized:
                stages["authorized"] = True
            if client.connected:
                stages["connected"] = True
            time.sleep(0.05)
        else:
            # timed out without job
            pass

        if got_job.is_set() and job_id:
            diff = client.server_set_difficulty or client.difficulty
            return PoolConnectionTestResult(
                ok=True,
                stage="job",
                message=(
                    f"OK — authorized and received mining.notify job_id={job_id} "
                    f"from {clean_host}:{clean_port}."
                ),
                host=clean_host,
                port=clean_port,
                job_id=job_id,
                difficulty=float(diff) if diff is not None else None,
                authorized=True,
            )

        if client.authorized or stages["authorized"]:
            return PoolConnectionTestResult(
                ok=False,
                stage="authorized",
                message=(
                    "Authorization succeeded, but no mining.notify/job was received "
                    f"within {timeout_s:.0f}s. TCP/auth/set_difficulty alone is not enough."
                ),
                host=clean_host,
                port=clean_port,
                authorized=True,
                difficulty=client.server_set_difficulty,
            )
        if client.connected or stages["connected"]:
            return PoolConnectionTestResult(
                ok=False,
                stage="connected",
                message=(
                    "TCP connected, but authorize or mining.notify did not complete. "
                    f"Password was {mask_secret(clean_pass)}."
                ),
                host=clean_host,
                port=clean_port,
            )
        note = status_notes[-1] if status_notes else "no stratum progress"
        return PoolConnectionTestResult(
            ok=False,
            stage="failed",
            message=f"Could not complete pool handshake: {note}",
            host=clean_host,
            port=clean_port,
        )
    except Exception as exc:
        return PoolConnectionTestResult(
            ok=False,
            stage="failed",
            message=f"Connection test error: {exc}",
            host=clean_host,
            port=clean_port,
        )
    finally:
        try:
            client.stop()
        except Exception:
            pass
        client_holder["c"] = None
