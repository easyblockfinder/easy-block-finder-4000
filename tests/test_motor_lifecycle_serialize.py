"""Durdur ∥ teandrymal / donation: engine_ops deadlock none, tek fold, stop afreandrsei start none."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.xmrig_runner import XmrigRunner, XmrigSnapshot  # noqa: E402
from mining.managed_counters import ManagedShareAccum  # noqa: E402
from worker.controller import MiningController  # noqa: E402


def _fake_runner(gen: int, accepted: int = 12) -> XmrigRunner:
    r = XmrigRunner(Path("xmrig.exe"), host="h", port=1, username="u", generation=gen)
    r._user_accepted = accepted
    r.snapshot = XmrigSnapshot(accepted=accepted, generation=gen)
    r.refresh_snapshot = MagicMock()  # type: ignore[method-assign]
    r.stop = MagicMock(return_value=True)  # type: ignore[method-assign]
    r.is_running = MagicMock(return_value=False)  # type: ignore[method-assign]
    return r


def test_stop_waits_for_thermal_halt_single_fold(tmp_path, monkeypatch):
    """
    Termal halt motor_ops tutarken UI stop bekler; tek fold; stop join kilitsiz.
    """
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    shares = ManagedShareAccum()
    c._share_accum = shares
    gen = shares.next_generation()
    c._motor_gen = gen
    shares.apply_snapshot(XmrigSnapshot(accepted=12, generation=gen), gen)
    r = _fake_runner(gen, 12)
    c._xmrig = r

    ready = threading.Barrier(2)
    stop_done = threading.Event()
    fold_count = {"n": 0}
    orig_retire = shares.retire_with_final

    def counting_retire(g, final):
        ok = orig_retire(g, final)
        if ok:
            fold_count["n"] += 1
        return ok

    shares.retire_with_final = counting_retire  # type: ignore[method-assign]

    def miner_thermal_halt():
        ready.wait(timeout=5)
        with c._motor_ops:
            time.sleep(0.12)  # stop this orderda engine_ops bekler
            c._retire_motor_into(shares, r, gen)
            c._stop_external(r, "XMRig", timeout_s=1.0)
            if c._xmrig is r:
                c._xmrig = None

    def user_stop():
        ready.wait(timeout=5)
        c._stopping = True
        c._stop.set()
        acquired = c._motor_ops.acquire(timeout=5)
        assert acquired, "engine_ops alinamadi (deadlock?)"
        try:
            c._fold_active_motor_shares()
            err = c._stop_external(c._xmrig, "XMRig", timeout_s=1.0)
            if err is None:
                c._xmrig = None
        finally:
            c._motor_ops.release()
        t_miner.join(timeout=5)
        stop_done.set()

    t_miner = threading.Thread(target=miner_thermal_halt, name="miner-sim")
    t_stop = threading.Thread(target=user_stop, name="ui-stop")
    t_miner.start()
    t_stop.start()
    t_stop.join(timeout=8)
    t_miner.join(timeout=2)
    assert stop_done.is_set(), "deadlock: stop tamamlanmadi"
    assert fold_count["n"] == 1
    assert shares.display_accepted == 12


def test_stop_blocks_restart_after_donation_halt(tmp_path, monkeypatch):
    """Durdur afreandrsei _start_xmrig engine acmamali."""
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    shares = ManagedShareAccum()
    c._share_accum = shares
    gen = shares.next_generation()
    c._motor_gen = gen
    r = _fake_runner(gen, 8)
    c._xmrig = r
    shares.apply_snapshot(r.snapshot, gen)

    barrier = threading.Barrier(2)
    started = {"n": 0}

    def donation_transition():
        barrier.wait()
        with c._motor_ops:
            c._retire_motor_into(shares, c._xmrig, c._motor_gen)
            if c._xmrig is not None:
                c._stop_external(c._xmrig, "XMRig", timeout_s=1.0)
                c._xmrig = None
            # Bnetworkis afreandrsei again start — stop gelmjobse engellenmeli
            if c._motor_start_blocked():
                return
            started["n"] += 1
            c._xmrig = _fake_runner(shares.next_generation(), 0)

    def user_stop():
        barrier.wait()
        c._stopping = True
        c._stop.set()
        with c._motor_ops:
            c._fold_active_motor_shares()
            if c._xmrig is not None:
                c._stop_external(c._xmrig, "XMRig", timeout_s=1.0)
                c._xmrig = None

    t1 = threading.Thread(target=donation_transition)
    t2 = threading.Thread(target=user_stop)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert started["n"] == 0
    assert c._xmrig is None or not c._xmrig.is_running()
    assert shares.display_accepted == 8


def test_controller_stop_does_not_deadlock_with_halt_holding_ops(tmp_path, monkeypatch):
    """Gercek MiningController.stop() + miner thread engine_ops — timeout none."""
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    shares = ManagedShareAccum()
    c._share_accum = shares
    gen = shares.next_generation()
    c._motor_gen = gen
    shares.apply_snapshot(XmrigSnapshot(accepted=5, generation=gen), gen)
    r = _fake_runner(gen, 5)
    c._xmrig = r

    hold = threading.Event()
    release = threading.Event()

    def miner_main():
        c._thread = threading.current_thread()
        with c._motor_ops:
            hold.set()
            release.wait(timeout=5)
            # stop join bekliyor; halt benzeri job
            c._retire_motor_into(shares, r, gen)

    t = threading.Thread(target=miner_main, name="miner-main")
    t.start()
    assert hold.wait(timeout=3)
    # stop() join ordersinda engine_ops tutmaz → miner leaand edebilir
    def unlock_after_stop_started():
        time.sleep(0.05)
        release.set()

    threading.Thread(target=unlock_after_stop_started, daemon=True).start()
    ok = c.stop()
    t.join(timeout=3)
    assert ok is True
    assert shares.display_accepted == 5
