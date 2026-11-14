from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.block_store import (  # noqa: E402
    NETWORK_UNKNOWN,
    BlockCandidateStore,
    STATUS_CANDIDATE,
    migrate_block_record,
)


def test_same_hash_different_networks(tmp_path: Path):
    path = tmp_path / "blocks.json"
    store = BlockCandidateStore(path=path)
    h = "ab" * 32
    store.enqueue_upsert(
        {
            "hash": h,
            "network_id": "btc",
            "chain_status": STATUS_CANDIDATE,
            "found_at": "2026-01-01 00:00:01",
        }
    )
    store.enqueue_upsert(
        {
            "hash": h,
            "network_id": "bch",
            "chain_status": STATUS_CANDIDATE,
            "found_at": "2026-01-01 00:00:02",
        }
    )
    deadline = time.time() + 3
    while time.time() < deadline:
        data = store.load()
        if len(data) >= 2:
            break
        time.sleep(0.05)
    store.stop()
    all_recs = json.loads(path.read_text(encoding="utf-8"))
    assert len(all_recs) == 2
    btc = store.load(network_id="btc")
    bch = store.load(network_id="bch")
    assert len(btc) == 1 and btc[0]["network_id"] == "btc"
    assert len(bch) == 1 and bch[0]["network_id"] == "bch"


def test_migrate_unknown_not_forced_btc():
    rec = migrate_block_record({"hash": "cd" * 32, "payout_address": ""})
    assert rec["network_id"] == NETWORK_UNKNOWN


def test_migrate_bc1_infers_btc():
    rec = migrate_block_record(
        {"hash": "ef" * 32, "payout_address": "bc1qexampleaddress0000000000000000000"}
    )
    assert rec["network_id"] == "btc"
