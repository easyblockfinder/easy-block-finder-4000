"""Background VRAM / network capability probe."""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal


class CapacityProbeWorker(QThread):
    finished_ok = pyqtSignal(object)  # dict[str, str|None]
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            from monitor.hardware_report import probe_network_capacity

            blocks = probe_network_capacity(include_vram=True)
            self.finished_ok.emit(blocks)
        except Exception as exc:
            self.failed.emit(str(exc))
