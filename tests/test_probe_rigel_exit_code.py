from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines import rigel_runner as rr  # noqa: E402


def test_nonzero_exit_raises_even_if_parseable(monkeypatch):
    text = (
        "Rigel 1.23.2\n"
        "GPU #0  [0000:01:00.0]  NVIDIA GeForce GTX 1650  4096 MB\n"
    )
    fake = MagicMock()
    fake.returncode = 1
    fake.stdout = text
    fake.stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
    with pytest.raises(RuntimeError, match="exit=1"):
        rr.probe_rigel_devices(Path("rigel.exe"))


def test_zero_exit_returns_devices(monkeypatch):
    text = (
        "Rigel 1.23.2\n"
        "GPU #0  [0000:01:00.0]  NVIDIA GeForce GTX 1650  4096 MB\n"
    )
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = text
    fake.stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
    devs = rr.probe_rigel_devices(Path("rigel.exe"))
    assert len(devs) == 1
