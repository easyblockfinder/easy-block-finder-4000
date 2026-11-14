"""Blok candidatei persistence (async) testleri."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.block_store import BlockCandidateStore, STATUS_CANDIDATE  # noqa: E402


def test_enqueue_upsert_persists(tmp_path: Path):
    path = tmp_path / "blocks.json"
    store = BlockCandidateStore(path=path)
    rec = {
        "hash": "ab" * 32,
        "job_id": "j1",
        "nonce_hex": "01020304",
        "extranonce2": "00" * 8,
        "ntime": "6af51cd7",
        "header80": "00" * 80,
        "payout_address": "bc1qexample",
        "chain_status": STATUS_CANDIDATE,
        "found_at": "2026-01-01 00:00:00",
    }
    store.enqueue_upsert(rec)
    # Writer async — bekle
    deadline = time.time() + 3
    while time.time() < deadline and not path.is_file():
        time.sleep(0.05)
    store.stop()
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0]["hash"] == rec["hash"]
    assert data[0]["chain_status"] == STATUS_CANDIDATE


def test_load_on_empty(tmp_path: Path):
    store = BlockCandidateStore(path=tmp_path / "missing.json")
    assert store.load() == []
    store.stop()
