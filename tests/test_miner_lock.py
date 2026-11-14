from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.fetch_miner import load_lock  # noqa: E402


def test_xmrig_lock_pin():
    lock = load_lock()
    x = lock["xmrig"]
    assert x["version"] == "6.26.0"
    assert len(x["sha256"]) == 64
    assert x["sha256"] == "bba8097cb37d9b458a1cb1137876b27cde6740d17fe4ccbc086ba07d87d9e147"
