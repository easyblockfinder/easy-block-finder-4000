from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from worker.controller import MiningController  # noqa: E402


def test_explorer_update_stopped_persists_not_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    c._stop.set()
    c._thread = None
    c.network_id = "btc"
    c.stats.block_candidates = [
        {"hash": "aa" * 32, "network_id": "btc", "chain_status": "aday_bulundu"}
    ]
    c._on_explorer_update(
        {
            "hash": "aa" * 32,
            "network_id": "btc",
            "chain_status": "ana_zincirde_dogrulandi",
            "chain_detail": "late",
        }
    )
    # UI listesi degjobmemeli (session durdu)
    assert c.stats.block_candidates[0]["chain_status"] == "aday_bulundu"
