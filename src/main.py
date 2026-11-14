"""Easy Block Finder 4000 entry point."""

from __future__ import annotations

import sys
import warnings
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
    app.setQuitOnLastWindowClosed(False)  # keep process alive when window closes to tray

    if not QSystemTrayIcon.isSystemTrayAvailable():
        # Classic quit-on-close when tray unavailable
        app.setQuitOnLastWindowClosed(True)

    guard = SingleInstanceGuard(app)
    if not guard.ensure_primary():
        # Another instance is running — it was asked to raise its window
        return 0

    win = MainWindow()
    guard.activated.connect(win.raise_to_front)
    app.aboutToQuit.connect(guard.close)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
