"""Windows Security / Defender — miner false-positive detection and guidance."""

from __future__ import annotations

import ctypes
import logging
import os
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


def solo_blockstrike_root() -> Path:
    """Backward-compatible alias → app_data_root()."""
    return app_data_root()


def clear_zone_identifier(path: Path) -> bool:
    """
    Remove Mark-of-the-Web (Zone.Identifier) ADS from internet-downloaded files.
    Reduces SmartScreen friction; does not remove signature-based Defender blocks.
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
        # 2 = ERROR_FILE_NOT_FOUND → no ADS, OK
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
        # Some wrappers only expose errno
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
        "Viri",
        "Access denied",
        "access is denied",
        "operation did not complete",
    )
    return any(n in msg for n in needles)


def exe_quarantined_or_missing(exe: Path) -> bool:
    try:
        p = Path(exe)
        if not p.is_file():
            return True
        # Unreadable (quarantine lock) counts as blocked
        with p.open("rb") as f:
            f.read(64)
        return False
    except OSError:
        return True


def defender_exclusion_help(miner_label: str = "XMRig") -> str:
    from app_meta import APP_NAME

    root = app_data_root()
    return (
        f"Windows Security may have blocked the {miner_label} engine "
        f"(CoinMiner false positive; {APP_NAME} uses SHA-256–pinned archives). "
        f"Windows Security → Virus & threat protection → Manage settings → "
        f"Exclusions → Add folder: "
        f"{root}  "
        f"Then restore quarantined xmrig.exe from Protection history. "
        f"Administrator PowerShell: scripts\\add_defender_exclusion.ps1"
    )
