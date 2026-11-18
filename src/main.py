"""Easy Block Finder 4000 entry point."""

from __future__ import annotations

import faulthandler
import sys
import traceback
import warnings
from datetime import datetime, timezone
from pathlib import Path

# Known console noise (legacy pynvml meta-package)
warnings.filterwarnings(
    "ignore",
    message=".*pynvml package is deprecated.*",
    category=FutureWarning,
)

# Add src/ root to sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _crash_log_path() -> Path:
    import os

    from app_meta import APP_DATA_DIRNAME

    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    folder = base / APP_DATA_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "crash.log"


def _install_crash_logging() -> None:
    """Persist uncaught exceptions / fatal traces so silent GUI exits leave a trail."""
    log_path = _crash_log_path()
    # Keep the file handle alive for the process lifetime (faulthandler needs it).
    global _CRASH_LOG_FH  # noqa: PLW0603
    try:
        _CRASH_LOG_FH = log_path.open("a", encoding="utf-8")
        faulthandler.enable(file=_CRASH_LOG_FH, all_threads=True)
    except Exception:
        try:
            faulthandler.enable()
        except Exception:
            pass

    def _hook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n===== {stamp} =====\n{text}")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


_CRASH_LOG_FH = None


def _force_light_palette(app) -> None:
    """
    Windows dark mode gives Qt a light text palette. Our UI uses light panels, so
    typed text / checkbox labels become invisible (white on white). Force a light
    Fusion palette so inputs stay readable regardless of OS theme.
    """
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtWidgets import QStyleFactory

    app.setStyle(QStyleFactory.create("Fusion") or app.style())
    pal = QPalette()
    window = QColor("#eef1f4")
    text = QColor("#15202b")
    base = QColor("#ffffff")
    mid = QColor("#c8d2dc")
    highlight = QColor("#0d9488")
    disabled = QColor("#6b7c8a")
    pal.setColor(QPalette.ColorRole.Window, window)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#f7f9fb"))
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, base)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.ToolTipBase, base)
    pal.setColor(QPalette.ColorRole.ToolTipText, text)
    pal.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Highlight, highlight)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#94a3b8"))
    pal.setColor(QPalette.ColorRole.Link, highlight)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, mid)
    app.setPalette(pal)


def main() -> int:
    _install_crash_logging()

    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

    from app_meta import APP_NAME, APP_VERSION, APP_VERSION_LABEL, load_app_icon
    from ui.main_window import MainWindow
    from ui.single_instance import SingleInstanceGuard

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_VERSION_LABEL)
    _force_light_palette(app)
    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    # Always keep process alive when the main window is hidden to tray.
    # (If tray is unavailable, closeEvent still quits via MainWindow.)
    app.setQuitOnLastWindowClosed(False)

    guard = SingleInstanceGuard(app)
    if not guard.ensure_primary():
        # Another instance is running — it was asked to raise its window.
        # Exit quietly; a MessageBox here would look like a crash to users.
        return 0

    try:
        win = MainWindow()
    except Exception:
        # Ensure startup failures land in crash.log, then re-raise
        raise
    guard.activated.connect(win.raise_to_front)
    app.aboutToQuit.connect(guard.close)
    # Stop LED timers, destroy tray overlay, wait for QThreads before teardown
    # (hidden main + visible Tool overlay / live workers caused native abort on quit).
    app.aboutToQuit.connect(win._teardown_for_quit)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
