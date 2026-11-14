"""Install root and AppData update staging (never miners/settings)."""

from __future__ import annotations

import os
from pathlib import Path

from app_meta import APP_DATA_DIRNAME, REPO_ROOT


def install_root() -> Path:
    """Directory that contains start.bat / src (the installed app tree)."""
    return Path(REPO_ROOT).resolve()


def appdata_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    folder = base / APP_DATA_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def updates_dir() -> Path:
    d = appdata_root() / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def staging_dir(version: str) -> Path:
    safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in version)
    d = updates_dir() / f"stage-{safe}"
    d.mkdir(parents=True, exist_ok=True)
    return d
