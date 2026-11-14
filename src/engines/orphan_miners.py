"""Find/kill external miner processes launched by the app (orphan protection)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
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


def _appdata_miners_marker() -> str:
    from app_meta import APP_DATA_DIRNAME

    base = os.environ.get("LOCALAPPDATA") or ""
    return (Path(base) / APP_DATA_DIRNAME / "miners").as_posix().lower()


def list_app_rigel() -> list[OrphanHit]:
    """Rigel launched from this app's AppData miners folder (or known API bind)."""
    if sys.platform != "win32":
        return []
    marker = _appdata_miners_marker()
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'rigel.exe'\" | "
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
        log.exception("orphan rigel list")
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
        cmd_l = cmd.replace("\\", "/").lower()
        if not cmd or not marker or marker not in cmd_l:
            continue
        try:
            pid = int(row.get("ProcessId"))
        except (TypeError, ValueError):
            continue
        hits.append(
            OrphanHit(pid=pid, name=str(row.get("Name") or ""), cmdline=cmd[:240])
        )
    return hits


def kill_app_rigel(*, exclude_pid: Optional[int] = None) -> tuple[int, list[int]]:
    hits = list_app_rigel()
    pids = [h.pid for h in hits if exclude_pid is None or h.pid != exclude_pid]
    if not pids:
        return 0, []
    failed = kill_pids(pids)
    killed = max(0, len(pids) - len(failed))
    if killed:
        log.warning("Orphaned Rigel terminated: pids=%s", pids)
    return killed, failed


def list_app_miners() -> list[OrphanHit]:
    return list_app_xmrig() + list_app_rigel()


def kill_app_miners(*, exclude_pid: Optional[int] = None) -> tuple[int, list[int]]:
    """Stop all EBF4000-managed external miners (XMRig + Rigel)."""
    n1, f1 = kill_app_xmrig(exclude_pid=exclude_pid)
    n2, f2 = kill_app_rigel(exclude_pid=exclude_pid)
    return n1 + n2, f1 + f2


# Retrospective alias
list_soloblockstrike_xmrig = list_app_xmrig
kill_soloblockstrike_xmrig = kill_app_xmrig
