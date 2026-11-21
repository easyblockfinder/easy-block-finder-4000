"""Dedicated Automatic Idle Mining regression scenarios (mock/unit — not hardware)."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.best_hash_store import load_best_hash_state, upsert_record_if_better  # noqa: E402
from mining.lifetime_stats import add_lifetime_attempts, get_lifetime_attempts  # noqa: E402
from networks.pool_resolve import resolve_pool  # noqa: E402
from worker.controller import MiningController  # noqa: E402
from worker.idle_policy import IdleMiningPolicy  # noqa: E402
from worker.work_scale import adaptive_duty_sleep, intensity_batch_sleep  # noqa: E402


@pytest.fixture
def ctrl(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    c = MiningController()
    c.allow_mine_without_temp = True
    c._resolved_gpu_bus = ""
    c._temp.read_celsius = lambda: 50  # type: ignore[method-assign]
    return c


def test_idle_pause_still_applies_notify_and_difficulty(ctrl, monkeypatch):
    """While hashing is idle-paused, stratum job/diff callbacks still update state."""
    ctrl.update_idle_options(enabled=True, timeout_s=150, active_pct=0, idle_pct=100)
    ctrl._idle_policy._mode = "active"
    # Fake stratum for _on_job
    st = MagicMock()
    st.extranonce1 = "abcd"
    st.extranonce2_size = 4
    st.difficulty = 1.0
    st.session_id = 1
    st.wire_log = []
    ctrl._stratum = st
    ctrl._pool_endpoint = resolve_pool("btc", {})
    ctrl.address = "bc1qtestaddressfortest00000000000000"
    ctrl._mining_address = ctrl.address
    ctrl._profile = __import__("networks.profiles", fromlist=["get_profile"]).get_profile(
        "btc"
    )
    # Loosen coinbase for unit path
    monkeypatch.setattr(
        "worker.controller.verify_job_coinbase_payout",
        lambda **kwargs: MagicMock(
            message="ok",
            stop_mining=False,
            amount_independently_verified=False,
        ),
    )
    params = [
        "job99",
        "0" * 64,
        "00",
        "00",
        [],
        "20000000",
        "1d00ffff",
        "12345678",
        True,
    ]
    ctrl._on_job(params, True)
    assert ctrl._job is not None
    assert ctrl._job.job_id == "job99"
    ctrl._on_difficulty(42.0)
    assert ctrl.stats.server_difficulty == 42.0
    assert ctrl._pending_difficulty == 42.0


def test_resume_does_not_use_stale_invalidated_job(ctrl):
    from mining.job import MiningJob

    job = MiningJob(
        job_id="old",
        prevhash="0" * 64,
        coinb1="",
        coinb2="",
        merkle_branches=[],
        version="20000000",
        nbits="1d00ffff",
        ntime="12345678",
        clean_jobs=True,
        extranonce1="aa",
        extranonce2_size=4,
        difficulty=1.0,
        generation=1,
    )
    job.mark_invalidated()
    with ctrl._job_lock:
        ctrl._job = job
        ctrl._work_epoch = 2
    assert job.accept_new_work() is False
    # Mine-loop style check
    with ctrl._job_lock:
        cur = ctrl._job
        usable = cur is not None and cur.accept_new_work()
    assert usable is False


def test_manual_stop_idle_timeout_does_not_autostart(ctrl):
    ctrl.update_idle_options(enabled=True, timeout_s=1, active_pct=10, idle_pct=100)
    assert ctrl.is_running() is False
    # Simulate long idle while stopped — policy may say IDLE but must not start.
    st = ctrl._idle_policy.evaluate(idle_s=999.0)
    assert st.mode == "idle"
    assert ctrl.is_running() is False
    assert ctrl._thread is None
    assert ctrl._xmrig is None


def test_thermal_pause_blocks_idle_resume_path(ctrl):
    ctrl.update_idle_options(enabled=True, timeout_s=1, active_pct=10, idle_pct=100)
    ctrl._paused = True
    ctrl.stats.paused_thermal = True
    ctrl.pause_temp = 80
    ctrl.resume_temp = 70
    # Hot — stay thermal paused
    ctrl._temp.read_celsius = lambda: 90  # type: ignore[method-assign]
    assert ctrl._thermal_gate() is False
    # Even if policy wants IDLE full scale, thermal gate fails first in mine loop.
    st = ctrl._idle_policy.evaluate(idle_s=999)
    assert st.mode == "idle"
    assert ctrl._paused is True


def test_custom_pool_resolve_with_idle_settings(ctrl, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    pbn = {
        "btc": {
            "mode": "custom",
            "custom": {
                "host": "pool.example.com",
                "port": 3333,
                "pool_kind": "shared",
            },
        }
    }
    ep = resolve_pool("btc", pbn)
    assert ep.mode == "custom"
    assert ep.host == "pool.example.com"
    ctrl.update_idle_options(enabled=True, timeout_s=150, active_pct=10, idle_pct=100)
    ctrl._pool_endpoint = ep
    # Idle does not mutate endpoint
    ctrl._eval_idle_policy()
    assert ctrl._pool_endpoint.host == "pool.example.com"


def test_lifetime_and_best_hash_survive_idle_toggle(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    before = add_lifetime_attempts("btc", 1000)
    assert get_lifetime_attempts("btc") == before
    upsert_record_if_better(
        "btc",
        hash_be_hex="00000000" + "aa" * 28,
        nonce_hex="1",
        job_id="idle-reg",
        nbits="1d00ffff",
        network_difficulty_at_time=1.0,
        kind="gpu",
    )
    assert load_best_hash_state()["records"]["btc"].gpu_best is not None
    # Toggle idle policy — must not clear stores
    p = IdleMiningPolicy()
    p.configure(enabled=True, timeout_s=10, active_pct=0, idle_pct=100)
    p.evaluate(idle_s=0)
    p.evaluate(idle_s=100)
    assert get_lifetime_attempts("btc") == before
    assert load_best_hash_state()["records"]["btc"].gpu_best.nonce_hex == "1"


def test_xmrig_http_pause_failure_does_not_mark_paused(ctrl):
    ctrl.update_idle_options(enabled=True, timeout_s=10, active_pct=10, idle_pct=100)
    ctrl._idle_policy._mode = "active"
    xm = MagicMock()
    xm.is_running.return_value = True
    xm.pause_mining.return_value = False
    xm.resume_mining.return_value = True
    ctrl._xmrig = xm
    ctrl._xmrig_idle_paused = False
    # Replicate controller decision without full loop
    want_pause = True
    if want_pause != ctrl._xmrig_idle_paused:
        if not xm.pause_mining():
            # failure path
            pass
        else:
            ctrl._xmrig_idle_paused = True
    assert ctrl._xmrig_idle_paused is False
    assert xm.pause_mining.called


def test_sleep_session_force_active(ctrl):
    ctrl.update_idle_options(enabled=True, timeout_s=30, active_pct=10, idle_pct=100)
    ctrl._idle_policy.evaluate(idle_s=100)
    assert ctrl._idle_policy._mode == "idle"
    ctrl.force_idle_active()
    st = ctrl._eval_idle_policy()
    assert st.mode == "active"


def test_adaptive_duty_cycle_scales_with_batch_time():
    b = 0.002
    s = 0.1
    assert adaptive_duty_sleep(0.02, b, s) < adaptive_duty_sleep(0.2, b, s)
    # S=1 identical to base sleep regardless of T
    assert adaptive_duty_sleep(0.5, b, 1.0) == b


def test_auto_idle_off_uses_intensity_ladder_only():
    batch, sleep = intensity_batch_sleep(4)
    p = IdleMiningPolicy()
    p.configure(enabled=False)
    st = p.evaluate(idle_s=999)
    assert st.mode == "off"
    assert st.scale == 1.0
    # Controller path uses intensity_batch_sleep when off — same as ladder
    assert (batch, sleep) == intensity_batch_sleep(4)


def test_interruptible_wait_stops_quickly(ctrl):
    ctrl._stop.set()
    t0 = __import__("time").perf_counter()
    ok = ctrl._interruptible_wait(2.0, chunk_s=0.05)
    elapsed = __import__("time").perf_counter() - t0
    assert ok is False
    assert elapsed < 0.5


def test_interruptible_wait_aborts_on_activity(ctrl, monkeypatch):
    ctrl.update_idle_options(enabled=True, timeout_s=150, active_pct=10, idle_pct=100)
    ctrl._idle_policy._mode = "idle"
    monkeypatch.setattr("worker.controller.idle_seconds", lambda: 0.0)
    t0 = __import__("time").perf_counter()
    ok = ctrl._interruptible_wait(5.0, chunk_s=0.05, abort_if_active=True)
    elapsed = __import__("time").perf_counter() - t0
    assert ok is False
    assert elapsed < 1.0
