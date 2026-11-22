"""XMRig donate pool → user accepted not."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.xmrig_runner import (  # noqa: E402
    XmrigRunner,
    format_xmrig_job_label,
    parse_xmrig_new_job,
)


def test_donate_pool_detection():
    r = XmrigRunner(
        Path("xmrig.exe"),
        host="xmr.kryptex.network",
        port=7029,
        username="solo:x",
        user_pool_hint="kryptex",
    )
    assert r._is_donate_pool("donate.xmrig.com:3333") is True
    assert r._is_donate_pool("xmr.kryptex.network:7029") is False
    assert r._classify_pool("") == "unattributed"
    assert r._is_donate_pool("") is False
    # Host matchmesi (hint string’i eandn without eandn)
    assert r._is_donate_pool("xmr.kryptex.network:7029") is False


def test_ingest_splits_fee_shares():
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
            "results": {"shares_good": 2, "shares_total": 2},
            "hashrate": {"total": [100.0]},
        }
    )
    assert r.snapshot.accepted == 2
    assert r.snapshot.engine_fee_shares == 0
    # Gecjob interval → unattrithisted (fee’ye definite not written)
    r._ingest(
        {
            "connection": {"pool": "donate.v2.xmrig.com:3333", "uptime": 12},
            "results": {"shares_good": 3, "shares_total": 3},
            "hashrate": {"total": [90.0]},
        }
    )
    assert r.snapshot.accepted == 2
    assert r.snapshot.unattributed_shares == 1
    assert r.snapshot.engine_fee_shares == 0
    assert r.snapshot.donating is True
    # Ayni donate in pool remaining increase → fee
    r._ingest(
        {
            "connection": {"pool": "donate.v2.xmrig.com:3333", "uptime": 20},
            "results": {"shares_good": 5, "shares_total": 5},
            "hashrate": {"total": [90.0]},
        }
    )
    assert r.snapshot.engine_fee_shares == 2
    assert r.snapshot.accepted == 2


def test_ingest_hashes_total_deltas():
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
            "results": {
                "shares_good": 0,
                "shares_total": 0,
                "hashes_total": 1_000_000,
            },
            "hashrate": {"total": [100.0]},
        }
    )
    assert r.snapshot.hashes_delta == 0  # baseline
    assert r.snapshot.hashes_total == 0
    r._ingest(
        {
            "connection": {"pool": "xmr.kryptex.network:7029", "uptime": 12},
            "results": {
                "shares_good": 0,
                "shares_total": 0,
                "hashes_total": 1_250_000,
            },
            "hashrate": {"total": [100.0]},
        }
    )
    assert r.snapshot.hashes_delta == 250_000
    assert r.snapshot.hashes_total == 250_000


def test_parse_xmrig_new_job_line():
    d, h = parse_xmrig_new_job(
        "[2024-01-01]  net      new job from xmr.kryptex.network:7029 "
        "diff 100001 algo rx/0 height 3123456"
    )
    assert d == 100001
    assert h == 3123456
    assert parse_xmrig_new_job("unrelated") == (None, None)
    assert format_xmrig_job_label(height=10, diff=99.0) == "height=10 · diff=99"


def test_ingest_sets_job_from_api_diff():
    r = XmrigRunner(
        Path("xmrig.exe"),
        host="xmr.kryptex.network",
        port=7029,
        username="solo:x",
        user_pool_hint="kryptex",
    )
    r._ingest(
        {
            "connection": {
                "pool": "xmr.kryptex.network:7029",
                "uptime": 10,
                "diff": 250000,
            },
            "results": {"shares_good": 0, "shares_total": 0, "diff_current": 250000},
            "hashrate": {"total": [50.0]},
        }
    )
    assert r.snapshot.difficulty == 250000.0
    assert "diff=250000" in r.snapshot.job_id
    r._note_job_from_log(
        "new job from xmr.kryptex.network:7029 diff 250000 algo rx/0 height 4000000"
    )
    assert "height=4000000" in r.snapshot.job_id
    assert "diff=250000" in r.snapshot.job_id
