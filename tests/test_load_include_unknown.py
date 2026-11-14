from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.block_store import NETWORK_UNKNOWN, BlockCandidateStore  # noqa: E402


def test_load_includes_unknown_when_requested(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    path = tmp_path / "block_candidates.json"
    path.write_text(
        json.dumps(
            [
                {"hash": "aa" * 32, "network_id": "btc"},
                {
                    "hash": "bb" * 32,
                    "network_id": NETWORK_UNKNOWN,
                    "payout_address": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
                },
                {"hash": "cc" * 32, "network_id": "bch"},
            ]
        ),
        encoding="utf-8",
    )
    store = BlockCandidateStore(path=path)
    only_btc = store.load(network_id="btc")
    assert len(only_btc) == 1
    with_unk = store.load(network_id="btc", include_unknown=True)
    assert len(with_unk) == 2
    assert any(r["network_id"] == NETWORK_UNKNOWN for r in with_unk)
