from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.block_store import ExplorerTracker  # noqa: E402


def test_btc_watch_not_queried_with_bch_endpoints(monkeypatch):
    calls: list[str] = []

    def fake_http(self, url: str):
        calls.append(url)
        raise TimeoutError("no net")

    monkeypatch.setattr(ExplorerTracker, "_http_json", fake_http)
    tr = ExplorerTracker(interval_s=0.01)
    tr.watch(
        {
            "hash": "aa" * 32,
            "network_id": "btc",
            "chain_status": "aday_bulundu",
        }
    )
    # Aktif UI BCH’ye gecse eandn configure tum watch’i degjobtirmemeli
    tr.configure(
        status_url="https://api.blockchair.com/bitcoin-cash/dashboards/block/{hash}",
        block_url="https://api.blockchair.com/bitcoin-cash/dashboards/block/{hash}",
        kind="blockchair_bch",
    )
    # Tek probe
    for rec in list(tr._watch.values()):
        tr._probe(rec)
    assert calls, "sorgu yapilmali"
    assert all("blockchair.com/bitcoin-cash" not in u for u in calls)
    assert all("blockstream.info" in u for u in calls)


def test_same_hash_different_networks_separate_keys():
    tr = ExplorerTracker()
    h = "bb" * 32
    tr.watch({"hash": h, "network_id": "btc"})
    tr.watch({"hash": h, "network_id": "bch"})
    assert len(tr._watch) == 2
    assert f"btc:{h}" in tr._watch
    assert f"bch:{h}" in tr._watch


def test_unknown_network_not_watched():
    tr = ExplorerTracker()
    tr.watch({"hash": "cc" * 32, "network_id": "unknown"})
    assert tr._watch == {}
