"""Windows Security / Defender — detect blocks and guide (no bypass)."""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Win32: Operation did not complete because the file contains a virus / was deleted
ERROR_VIRUS_INFECTED = 225
ERROR_VIRUS_DELETED = 226
ERROR_ACCESS_DENIED = 5
ERROR_CANCELLED = 1223


def app_data_root() -> Path:
    from app_meta import APP_DATA_DIRNAME

    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / APP_DATA_DIRNAME


def miners_exclusion_path() -> Path:
    """Narrow folder to exclude — only downloaded engines, not the whole profile."""
    return app_data_root() / "miners"


def solo_blockstrike_root() -> Path:
    """Backward-compatible alias → app_data_root()."""
    return app_data_root()


def clear_zone_identifier(path: Path) -> bool:
    """
    Remove Mark-of-the-Web (Zone.Identifier) ADS from internet-downloaded files.
    Reduces SmartScreen friction only; does not disable Defender signatures.
    """
    if os.name != "nt":
        return False
    try:
        path = Path(path)
        if not path.exists():
            return False
        ads = str(path.resolve()) + ":Zone.Identifier"
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if kernel32.DeleteFileW(ads):
            return True
        err = ctypes.get_last_error()
        if err == 2:
            return True
        log.debug("Could not delete Zone.Identifier %s err=%s", path.name, err)
        return False
    except Exception:
        log.debug("clear_zone_identifier", exc_info=True)
        return False


def winerror_code(exc: BaseException) -> Optional[int]:
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) is not None:
        return int(exc.winerror)
    if isinstance(exc, OSError) and exc.errno is not None and os.name == "nt":
        return int(exc.errno)
    return None


def looks_like_defender_block(exc: BaseException) -> bool:
    code = winerror_code(exc)
    if code in (
        ERROR_VIRUS_INFECTED,
        ERROR_VIRUS_DELETED,
        ERROR_ACCESS_DENIED,
        ERROR_CANCELLED,
    ):
        return True
    msg = str(exc).lower()
    needles = (
        "virus",
        "trojan",
        "defender",
        "antivirus",
        "quarantine",
        "evil",
        "pest",
        "access denied",
        "access is denied",
        "operation did not complete",
        "coinminer",
    )
    return any(n in msg for n in needles)


def exe_quarantined_or_missing(exe: Path) -> bool:
    try:
        p = Path(exe)
        if not p.is_file():
            return True
        with p.open("rb") as f:
            f.read(64)
        return False
    except OSError:
        return True


def ensure_miners_dir() -> Path:
    p = miners_exclusion_path()
    p.mkdir(parents=True, exist_ok=True)
    return p


def open_windows_security() -> bool:
    """Open Windows Security UI (user adds exclusion themselves)."""
    if os.name != "nt":
        return False
    try:
        os.startfile("windowsdefender:")  # type: ignore[attr-defined]
        return True
    except OSError:
        pass
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", "ms-settings:windowsdefender"],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        log.debug("open_windows_security failed", exc_info=True)
        return False


def open_exclusion_script_elevated() -> bool:
    """
    Launch scripts/add_defender_exclusion.ps1 with UAC (Add-MpPreference).
    User must approve the elevation prompt — Defender is not disabled.
    """
    if os.name != "nt":
        return False
    script = Path(__file__).resolve().parents[2] / "scripts" / "add_defender_exclusion.ps1"
    if not script.is_file():
        return False
    try:
        ensure_miners_dir()
        # runas → UAC; official Add-MpPreference inside the script
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "powershell.exe",
            f'-NoProfile -ExecutionPolicy Bypass -File "{script}"',
            str(script.parent),
            1,
        )
        return True
    except Exception:
        log.debug("open_exclusion_script_elevated", exc_info=True)
        return False


def defender_exclusion_help(miner_label: str = "XMRig") -> str:
    from app_meta import APP_NAME

    folder = miners_exclusion_path()
    return (
        f"Windows Security may have blocked {miner_label} "
        f"(common CoinMiner false positive; {APP_NAME} uses SHA-256–pinned official builds). "
        f"Do NOT turn Defender off. Instead: "
        f"(1) Exclusions → Add folder → {folder}  "
        f"(2) Protection history → Restore the quarantined file  "
        f"(3) Start mining again. "
        f"In the app you can open Windows Security or run the exclusion helper (UAC)."
    )


def defender_steps_plain(miner_label: str = "XMRig") -> str:
    folder = str(miners_exclusion_path())
    return (
        f"{miner_label} was blocked by Windows Security (often a false positive).\n\n"
        f"Keep Defender ON. Do only this:\n\n"
        f"1. Add an exclusion for this folder only:\n"
        f"   {folder}\n\n"
        f"2. Windows Security → Protection history → Restore the quarantined miner.\n\n"
        f"3. Press Start again in Easy Block Finder 4000.\n\n"
        f"Tip: “Open Windows Security” or “Add exclusion (UAC)” below."
    )
