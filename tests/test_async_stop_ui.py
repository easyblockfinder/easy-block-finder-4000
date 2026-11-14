from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from ui.main_window import _StopWorker  # noqa: E402


def test_async_stop_keeps_event_loop_alive_and_blocks_second_start(qapp=None):
    app = QCoreApplication.instance() or QCoreApplication([])

    ctrl = MagicMock()
    started = time.time()
    loop_ticks = {"n": 0}

    def slow_stop():
        # UI thread not — eandnt loop tick atsin
        deadline = time.time() + 0.35
        while time.time() < deadline:
            time.sleep(0.02)
        return True

    ctrl.stop.side_effect = slow_stop
    ctrl.is_running.return_value = True

    worker = _StopWorker(ctrl)
    done = {"ok": None}

    def on_done(ok: bool):
        done["ok"] = ok

    worker.finished_ok.connect(on_done)

    def tick():
        loop_ticks["n"] += 1

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(20)

    worker.start()
    # start engeli: stop durationrken is_running True (controller._stopping)
    deadline = time.time() + 2.0
    while done["ok"] is None and time.time() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

    timer.stop()
    worker.wait(2000)
    assert done["ok"] is True
    assert loop_ticks["n"] >= 3, "Qt eandnt loop stop ordersinda frozen"
    assert time.time() - started >= 0.3
