from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engines.rigel_runner import RigelRunner  # noqa: E402
from engines.xmrig_runner import XmrigRunner  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def test_xmrig_pool_transition_delta_is_unattributed():
    """
    XMRig results.shares_* process geneli. Kullmomentci→donate transitionindeki
    increase definite siniflandirilamaz → unattrithisted.
    Fixture: XMRig 6.x /2/summary semasi (hassas alan none).
    """
    r = XmrigRunner(
        Path("xmrig.exe"),
        host="xmr.kryptex.network",
        port=7029,
        username="solo:x",
        user_pool_hint="kryptex",
    )
    user = json.loads((FIX / "xmrig_summary_user_pool.json").read_text(encoding="utf-8"))
    donate = json.loads(
        (FIX / "xmrig_summary_donate_pool.json").read_text(encoding="utf-8")
    )
    r._ingest(user)
    assert r.snapshot.accepted == 5
    assert r.snapshot.engine_fee_shares == 0
    r._ingest(donate)  # good 5→7, pool degjobti
    assert r.snapshot.accepted == 5
    assert r.snapshot.unattributed_shares == 2
    assert r.snapshot.engine_fee_shares == 0


def test_xmrig_counter_reset_no_negative_invent():
    r = XmrigRunner(
        Path("xmrig.exe"),
        host="xmr.kryptex.network",
        port=7029,
        username="solo:x",
        user_pool_hint="kryptex",
    )
    r._ingest(
        {
            "connection": {"pool": "xmr.kryptex.network:7029", "uptime": 10},
            "results": {"shares_good": 10, "shares_total": 10},
            "hashrate": {"total": [1.0]},
        }
    )
    assert r.snapshot.accepted == 10
    # Reset
    r._ingest(
        {
            "connection": {"pool": "xmr.kryptex.network:7029", "uptime": 1},
            "results": {"shares_good": 0, "shares_total": 0},
            "hashrate": {"total": [1.0]},
        }
    )
    assert r.snapshot.accepted == 10  # eski birikim process-local; delta 0
    r._ingest(
        {
            "connection": {"pool": "xmr.kryptex.network:7029", "uptime": 2},
            "results": {"shares_good": 1, "shares_total": 1},
            "hashrate": {"total": [1.0]},
        }
    )
    assert r.snapshot.accepted == 11


def test_rigel_transition_unattributed():
    r = RigelRunner(
        Path("rigel.exe"),
        algorithm="kawpow",
        coin="rvn",
        host="solo-rvn.2miners.com",
        port=7070,
        username="u",
        user_pool_hint="2miners",
    )
    user = json.loads((FIX / "rigel_api_1_23_2_user.json").read_text(encoding="utf-8"))
    fee = json.loads((FIX / "rigel_api_1_23_2_fee.json").read_text(encoding="utf-8"))
    r._ingest(user)
    assert r.snapshot.accepted == 4
    r._ingest(fee)  # 4→6 transition
    assert r.snapshot.accepted == 4
    assert r.snapshot.unattributed_shares == 2
    # Ayni fee in pool remaining increase → fee
    fee2 = dict(fee)
    fee2["shares"] = {"accepted": 7, "rejected": 1, "invalid": 0}
    r._ingest(fee2)
    assert r.snapshot.engine_fee_shares == 1
