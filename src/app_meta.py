"""App name and version — single source."""

from __future__ import annotations

from pathlib import Path

APP_NAME = "Easy Block Finder 4000"
APP_SHORT = "EBF4000"
APP_VERSION = "1.0.1"
# Version label shown to the user
APP_VERSION_LABEL = f"{APP_SHORT} - v{APP_VERSION}"
# window / tray
APP_TITLE = f"{APP_NAME} ({APP_VERSION_LABEL})"
# HTTP User-Agent / stratum subscribe
APP_USER_AGENT = f"{APP_SHORT}/{APP_VERSION}"
# Data folder under %LOCALAPPDATA%
APP_DATA_DIRNAME = "EasyBlockFinder4000"
# Previous installations (settings / block candidate migration)
LEGACY_APP_DATA_DIRNAMES = ("SoloBlockStrike", "BTCHunter")
# XMRig HTTP API access token (cmdline orphan scan)
XMRIG_HTTP_TOKEN = "ebf4000"
# Orphan scan: new + legacy tokens
XMRIG_ORPHAN_TOKENS = (XMRIG_HTTP_TOKEN, "soloblockstrike")
XMRIG_HTTP_PORT = 40789

# Brand assets (repo root /assets)
REPO_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = REPO_ROOT  # back-compat
ASSETS_DIR = REPO_ROOT / "assets"
ICON_PATH = ASSETS_DIR / "ebf4000_icon.png"
LOGO_PATH = ASSETS_DIR / "ebf4000_logo.png"


def load_app_icon():
    """QIcon for window / tray / application."""
    from PyQt6.QtGui import QIcon

    if ICON_PATH.is_file():
        return QIcon(str(ICON_PATH))
    return QIcon()


def load_app_logo_pixmap(max_width: int = 420, max_height: int = 120):
    """Full wordmark logo scaled for headers."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPixmap

    if not LOGO_PATH.is_file():
        return QPixmap()
    pix = QPixmap(str(LOGO_PATH))
    if pix.isNull():
        return pix
    return pix.scaled(
        max_width,
        max_height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
