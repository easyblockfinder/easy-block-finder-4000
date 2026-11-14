"""Single-instance guard: second process notifies primary instead of opening UI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtNetwork import QLocalServer  # noqa: E402

from ui.single_instance import SERVER_NAME, SingleInstanceGuard  # noqa: E402


@pytest.fixture
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    QLocalServer.removeServer(SERVER_NAME)
    yield app
    QLocalServer.removeServer(SERVER_NAME)


def test_primary_acquires(qapp):
    g = SingleInstanceGuard()
    assert g.ensure_primary() is True
    g.close()


def test_second_yields_and_activates_primary(qapp):
    primary = SingleInstanceGuard()
    assert primary.ensure_primary() is True
    seen = {"n": 0}
    primary.activated.connect(lambda: seen.__setitem__("n", seen["n"] + 1))

    secondary = SingleInstanceGuard()
    assert secondary.ensure_primary() is False

    # Process queued connection / signal
    qapp.processEvents()
    assert seen["n"] >= 1

    primary.close()
    secondary.close()
