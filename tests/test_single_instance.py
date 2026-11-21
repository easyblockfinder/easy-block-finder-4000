"""Single-instance guard: second process notifies primary instead of opening UI."""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtNetwork import QLocalServer  # noqa: E402

from ui import single_instance as si  # noqa: E402
from ui.single_instance import SingleInstanceGuard  # noqa: E402


@pytest.fixture
def qapp(monkeypatch):
    """
    Isolate IPC name from any running EBF4000 instance and from other tests.
    Shared production SERVER_NAME made these tests flaky when the app was open.
    """
    name = f"EBF4000-pytest-si-{uuid.uuid4().hex}"
    monkeypatch.setattr(si, "SERVER_NAME", name)
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    QLocalServer.removeServer(si.SERVER_NAME)
    yield app
    QLocalServer.removeServer(si.SERVER_NAME)


def test_primary_acquires(qapp):
    g = SingleInstanceGuard()
    try:
        assert g.ensure_primary() is True
        assert g._server is not None
        assert g._server.isListening()
    finally:
        g.close()


def test_second_yields_and_activates_primary(qapp):
    primary = SingleInstanceGuard()
    secondary = SingleInstanceGuard()
    try:
        assert primary.ensure_primary() is True
        seen = {"n": 0}
        primary.activated.connect(lambda: seen.__setitem__("n", seen["n"] + 1))

        assert secondary.ensure_primary() is False

        # Drain queued socket → activated without depending on a single processEvents.
        deadline = time.monotonic() + 2.0
        while seen["n"] < 1 and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        assert seen["n"] >= 1
    finally:
        primary.close()
        secondary.close()
