"""poll∥refresh reandrse order HTTP → old response rejected (gaps §1)."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.rigel_runner import RigelRunner  # noqa: E402
from engines.xmrig_runner import XmrigRunner  # noqa: E402


def _xmrig_summary(good: int, total: int | None = None) -> dict:
    t = total if total is not None else good
    return {
        "connection": {"pool": "xmr.kryptex.network:7029", "uptime": 10},
        "results": {"shares_good": good, "shares_total": t},
        "hashrate": {"total": [100.0]},
    }


def _rigel_data(acc: int, rej: int = 0) -> dict:
    return {
        "pool": "rvn.2miners.com:6060",
        "hr_total": 10.0,
        "shares": {"accepted": acc, "rejected": rej},
    }


def test_xmrig_stale_api_rejected_out_of_order():
    """
    10 → 12 → stale 10 → 14: user accepted 14 kalmali (16 not).
    Iki HTTP cevabi kontrollu reandrse orderda apply_api_result with uygulmomentr.
    """
    r = XmrigRunner(
        Path("xmrig.exe"),
        host="xmr.kryptex.network",
        port=7029,
        username="solo:x",
        user_pool_hint="kryptex",
    )
    t1 = r._begin_api_request()
    assert t1 == 1
    assert r.apply_api_result(t1, _xmrig_summary(10)) is True
    assert r.snapshot.accepted == 10

    t2 = r._begin_api_request()
    assert t2 == 2
    assert r.apply_api_result(t2, _xmrig_summary(12)) is True
    assert r.snapshot.accepted == 12

    # Gecikmjob old response (ticket 1) — should be rejected; 10→reset smomentlmamali
    assert r.apply_api_result(t1, _xmrig_summary(10)) is False
    assert r.snapshot.accepted == 12

    t3 = r._begin_api_request()
    assert r.apply_api_result(t3, _xmrig_summary(14)) is True
    assert r.snapshot.accepted == 14


def test_xmrig_concurrent_poll_refresh_late_loses():
    """Yenisi uygulmomentr; stale old ticket rejected → 14 (16 not)."""
    r = XmrigRunner(
        Path("xmrig.exe"),
        host="xmr.kryptex.network",
        port=7029,
        username="solo:x",
        user_pool_hint="kryptex",
    )
    r.apply_api_result(r._begin_api_request(), _xmrig_summary(10))
    r.apply_api_result(r._begin_api_request(), _xmrig_summary(12))

    old_t = r._begin_api_request()
    new_t = r._begin_api_request()
    new_done = threading.Event()
    results: dict[str, bool] = {}

    def apply_new():
        results["new"] = r.apply_api_result(new_t, _xmrig_summary(14))
        new_done.set()

    def apply_old():
        assert new_done.wait(timeout=5)
        results["old"] = r.apply_api_result(old_t, _xmrig_summary(10))

    t_new = threading.Thread(target=apply_new)
    t_old = threading.Thread(target=apply_old)
    t_old.start()
    t_new.start()
    t_new.join()
    t_old.join()
    assert results["new"] is True
    assert results["old"] is False
    assert r.snapshot.accepted == 14


def test_rigel_stale_api_rejected_out_of_order():
    r = RigelRunner(
        Path("rigel.exe"),
        algorithm="kawpow",
        coin="rvn",
        host="rvn.2miners.com",
        port=6060,
        username="u",
        user_pool_hint="2miners",
    )
    t1 = r._begin_api_request()
    assert r.apply_api_result(t1, _rigel_data(10)) is True
    t2 = r._begin_api_request()
    assert r.apply_api_result(t2, _rigel_data(12)) is True
    assert r.apply_api_result(t1, _rigel_data(10)) is False
    assert r.snapshot.accepted == 12
    t3 = r._begin_api_request()
    assert r.apply_api_result(t3, _rigel_data(14)) is True
    assert r.snapshot.accepted == 14


def test_xmrig_error_ticket_consumes_so_late_success_rejected():
    """Yeni ticket hata → eski ticket success uygulanmaz (reset/over-count yok)."""
    r = XmrigRunner(
        Path("xmrig.exe"),
        host="xmr.kryptex.network",
        port=7029,
        username="solo:x",
        user_pool_hint="kryptex",
    )
    assert r.apply_api_result(r._begin_api_request(), _xmrig_summary(12)) is True
    assert r.snapshot.accepted == 12

    old_t = r._begin_api_request()
    new_t = r._begin_api_request()
    # Yeni istegin error yolu ticket consumes
    with r._lock:
        assert new_t > r._api_applied
        r._api_applied = new_t
        r.snapshot.status = "XMRig API bekleniyor: simulated"
    assert r.apply_api_result(old_t, _xmrig_summary(10)) is False
    assert r.snapshot.accepted == 12
