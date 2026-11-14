"""Background threads for update check / download (UI stays responsive)."""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from update.github_release import ReleaseLookupError
from update.service import (
    PreparedUpdate,
    UpdateError,
    UpdateOffer,
    check_for_update,
    prepare_update,
)


class UpdateCheckWorker(QThread):
    finished_ok = pyqtSignal(object)  # UpdateOffer | None
    failed = pyqtSignal(str)

    def __init__(self, *, force: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.force = force

    def run(self) -> None:
        try:
            offer = check_for_update()
            self.finished_ok.emit(offer)
        except ReleaseLookupError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdatePrepareWorker(QThread):
    progress = pyqtSignal(str, int, object)  # phase, received, total
    finished_ok = pyqtSignal(object)  # PreparedUpdate
    failed = pyqtSignal(str)

    def __init__(self, offer: UpdateOffer, parent=None) -> None:
        super().__init__(parent)
        self.offer = offer

    def run(self) -> None:
        try:
            def cb(phase: str, received: int, total) -> None:
                self.progress.emit(phase, received, total)

            prepared = prepare_update(self.offer, progress=cb)
            self.finished_ok.emit(prepared)
        except (UpdateError, ReleaseLookupError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))
