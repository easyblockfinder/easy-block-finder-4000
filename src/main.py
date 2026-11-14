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


def main() -> int:
    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

    from app_meta import APP_NAME, APP_VERSION, APP_VERSION_LABEL, load_app_icon
    from ui.main_window import MainWindow
    from ui.single_instance import SingleInstanceGuard

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_VERSION_LABEL)
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
