"""Find/kill external miner processes launched by the app (orphan protection)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

from app_meta import XMRIG_HTTP_PORT, XMRIG_ORPHAN_TOKENS

log = logging.getLogger(__name__)


@dataclass
class OrphanHit:
    pid: int
    name: str
    cmdline: str


def _xmrig_markers() -> tuple[str, ...]:
    marks = [f"--http-access-token={t}" for t in XMRIG_ORPHAN_TOKENS]
    marks.append(f"--http-port={XMRIG_HTTP_PORT}")
    return tuple(marks)


def list_app_xmrig() -> list[OrphanHit]:
    if sys.platform != "win32":
        return []
    markers = _xmrig_markers()
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'xmrig.exe'\" | "
        "Select-Object ProcessId, Name, CommandLine | ConvertTo-Json -Compress"
    )
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True,
            timeout=15,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        log.exception("orphan xmrig list")
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    hits: list[OrphanHit] = []
    for row in data or []:
        cmd = str(row.get("CommandLine") or "")
        if not cmd or not any(m in cmd for m in markers):
            continue
        try:
            pid = int(row.get("ProcessId"))
        except (TypeError, ValueError):
            continue
        hits.append(
            OrphanHit(pid=pid, name=str(row.get("Name") or ""), cmdline=cmd[:240])
        )
    return hits


def kill_pids(pids: list[int], *, timeout_s: float = 5.0) -> list[int]:
    """List of PIDs that cannot be terminated."""
    failed: list[int] = []
    for pid in pids:
        if pid <= 0 or pid == os.getpid():
            continue
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    check=False,
                    timeout=timeout_s,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                os.kill(pid, 15)
        except Exception:
            log.exception("kill pid=%s", pid)
            failed.append(pid)
            continue
        try:
            if sys.platform == "win32":
                r = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if str(pid) in (r.stdout or ""):
                    failed.append(pid)
        except Exception:
            pass
    return failed


def kill_app_xmrig(*, exclude_pid: Optional[int] = None) -> tuple[int, list[int]]:
    """
    Kill app-signed xmrig.exe processes.
    Returns: (killed_count, failed_pids)
    """
    hits = list_app_xmrig()
    pids = [h.pid for h in hits if exclude_pid is None or h.pid != exclude_pid]
    if not pids:
        return 0, []
    failed = kill_pids(pids)
    killed = max(0, len(pids) - len(failed))
    if killed:
        log.warning("Orphaned XMRig terminated: pids=%s", pids)
    return killed, failed


# Retrospective alias
list_soloblockstrike_xmrig = list_app_xmrig
kill_soloblockstrike_xmrig = kill_app_xmrig
