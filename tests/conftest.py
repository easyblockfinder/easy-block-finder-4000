"""Test izolasyonu: real SoloBlockStrike block_candidates / explorer'a yazilmasin."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.block_store import BlockCandidateStore  # noqa: E402
from worker.controller import MiningController  # noqa: E402


@pytest.fixture(autouse=True)
def _redirect_user_block_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Tum testler real %LOCALAPPDATA%/SoloBlockStrike dosyasindan uzak."""
    isolated = tmp_path / "isolated_user_store"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(isolated))


@pytest.fixture
def isolated_controller(tmp_path: Path):
    """
    MiningController + tmp block store + mock explorer.
    Gercek user dosyasina and network explorerne dokunmaz.
    """

    created: list = []

    def _factory(**kwargs):
        ctrl = MiningController(**kwargs)
        try:
            ctrl._explorer.stop()
        except Exception:
            pass
        try:
            ctrl._block_store.stop()
        except Exception:
            pass
        ctrl._block_store = BlockCandidateStore(path=tmp_path / "block_candidates.json")
        explorer = MagicMock()
        explorer.watch = MagicMock()
        explorer.start = MagicMock()
        explorer.stop = MagicMock()
        ctrl._explorer = explorer
        created.append(ctrl)
        return ctrl

    yield _factory

    for ctrl in created:
        try:
            ctrl._explorer.stop()
        except Exception:
            pass
        try:
            ctrl._block_store.stop()
        except Exception:
            pass
