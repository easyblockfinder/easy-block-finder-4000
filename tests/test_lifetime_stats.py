from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.lifetime_stats import (  # noqa: E402
    add_lifetime_attempts,
    get_lifetime_attempts,
    load_lifetime_stats,
)


def test_lifetime_add_and_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert get_lifetime_attempts("btc") == 0
    assert add_lifetime_attempts("btc", 100) == 100
    assert add_lifetime_attempts("btc", 50) == 150
    assert get_lifetime_attempts("bch") == 0
    assert load_lifetime_stats()["btc"] == 150
