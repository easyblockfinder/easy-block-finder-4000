"""Background thread for official miner downloads."""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal


class MinerDownloadWorker(QThread):
    progress = pyqtSignal(str, str, int, object, str)  # miner_id, phase, recv, total, detail
    miner_started = pyqtSignal(str, int, int)  # miner_id, index_1based, total
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str, str)  # miner_id, message

    def __init__(self, miner_ids: list[str], parent=None) -> None:
        super().__init__(parent)
        self.miner_ids = list(miner_ids)

    def run(self) -> None:
        from engines.fetch_miner import ensure_miner

        total = len(self.miner_ids)
        for i, miner_id in enumerate(self.miner_ids, start=1):
            self.miner_started.emit(miner_id, i, total)

            def _cb(
                phase: str,
                received: int,
                total_b,
                detail: str,
                _mid: str = miner_id,
            ) -> None:
                self.progress.emit(_mid, phase, received, total_b, detail)

            try:
                ensure_miner(
                    miner_id,
                    reverify=True,
                    require_consent=True,
                    progress=_cb,
                )
            except Exception as exc:
                self.failed.emit(miner_id, str(exc))
                return
        self.finished_ok.emit()
