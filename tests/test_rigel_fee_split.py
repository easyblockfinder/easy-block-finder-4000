from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.rigel_runner import RigelRunner  # noqa: E402


def test_rigel_fee_vs_user_pool():
    r = RigelRunner(
        Path("rigel.exe"),
        algorithm="kawpow",
        coin="rvn",
        host="solo-rvn.2miners.com",
        port=7070,
        username="Raddr",
        user_pool_hint="2miners",
    )
    assert r._is_fee_pool("solo-rvn.2miners.com:7070") is False
    assert r._is_fee_pool("fee.rigelminer.com:3333") is True
    assert r._is_fee_pool("") is True  # empty → user accepted does not inflate
    assert r._classify_pool("") == "unattributed"
    r._ingest(
        {
            "hr_total": 10.0,
            "shares": {"accepted": 2, "rejected": 0},
            "pool": "solo-rvn.2miners.com:7070",
        }
    )
    assert r.snapshot.accepted == 2
    r._ingest(
        {
            "hr_total": 10.0,
            "shares": {"accepted": 3, "rejected": 0},
            "pool": "devfee.example:3333",
        }
    )
    assert r.snapshot.accepted == 2
    assert r.snapshot.unattributed_shares == 1  # transition interval
    assert r.snapshot.engine_fee_shares == 0
    r._ingest(
        {
            "hr_total": 10.0,
            "shares": {"accepted": 4, "rejected": 0},
            "pool": "devfee.example:3333",
        }
    )
    assert r.snapshot.engine_fee_shares == 1
    assert r.snapshot.accepted == 2
