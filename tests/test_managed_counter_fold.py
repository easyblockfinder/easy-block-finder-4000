from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.rigel_runner import RigelRunner, RigelSnapshot  # noqa: E402
from engines.xmrig_runner import XmrigRunner, XmrigSnapshot  # noqa: E402
from mining.managed_counters import ManagedShareAccum  # noqa: E402


@dataclass
class _Snap:
    accepted: int = 0
    rejected: int = 0
    engine_fee_shares: int = 0
    unattributed_shares: int = 0


def test_retire_fold_late_callback_no_double_count():
    """Fold + retiredlik afreandrsei late callback 22 or 10 urso it does not → 12."""
    acc = ManagedShareAccum()
    gen = acc.next_generation()
    seen: list[int] = []

    def push():
        seen.append(acc.display_accepted)

    assert acc.apply_snapshot(_Snap(accepted=10), gen)
    push()
    assert seen[-1] == 10

    # stop ordersinda son snapshot 12; retire a kez fold eder
    final = _Snap(accepted=12)
    assert acc.retire_with_final(gen, final)
    push()
    assert seen[-1] == 12

    # Eski poller late callback accepted=12 (veya 14) — reddedilmeli
    assert acc.apply_snapshot(_Snap(accepted=14), gen) is False
    push()
    assert seen[-1] == 12

    # Yeni engine gen=2, sifirdan
    gen2 = acc.next_generation()
    assert acc.apply_snapshot(_Snap(accepted=0), gen2)
    push()
    assert seen[-1] == 12
    assert 22 not in seen
    assert seen == [10, 12, 12, 12]


def test_xmrig_retire_blocks_callback():
    r = XmrigRunner(Path("xmrig.exe"), host="h", port=1, username="u", generation=7)
    hits = []

    def cb(snap):
        hits.append(snap.accepted)

    r.on_snapshot = cb
    r._user_accepted = 10
    r.snapshot = XmrigSnapshot(accepted=10, generation=7)
    # ingest yolu: retire afreandrsei callback none
    r.retire()
    r._ingest(
        {
            "connection": {"pool": "h:1", "uptime": 1},
            "results": {"shares_good": 12, "shares_total": 12},
            "hashrate": {"total": [1.0]},
        }
    )
    assert hits == []
    assert r.snapshot.accepted >= 0  # ic counter guncellenebilir ama callback none
    final = r.take_final_snapshot()
    assert final.generation == 7


def test_xmrig_stop_emits_no_callback_after_retire_then_fold_12():
    """Mock: stop forde son 12’lik durum; accum 12; new engine 0 → display 12."""
    acc = ManagedShareAccum()
    gen = acc.next_generation()
    r = XmrigRunner(Path("xmrig.exe"), host="h", port=1, username="u", generation=gen)

    def on_snap(snap):
        acc.apply_snapshot(snap, snap.generation)

    r.on_snapshot = on_snap
    r._user_accepted = 10
    r.snapshot = XmrigSnapshot(accepted=10, generation=gen)
    acc.apply_snapshot(r.snapshot, gen)

    displays: list[int] = [acc.display_accepted]

    def fake_stop(timeout_s=8.0):
        # Yaris: stop ordersinda “son” 12
        r._user_accepted = 12
        r.snapshot = XmrigSnapshot(accepted=12, generation=gen)
        if r.on_snapshot and not r._retired:
            r.on_snapshot(r.snapshot)
        proc = MagicMock()
        proc.poll.return_value = 0
        r._proc = proc
        return True

    # Dogru order: before retire + final fold, after stop
    r.retire()
    final = XmrigSnapshot(accepted=12, generation=gen)
    acc.retire_with_final(gen, final)
    displays.append(acc.display_accepted)
    r.stop = fake_stop  # type: ignore[method-assign]
    r.stop()
    # Late callback (emekli gen)
    late = XmrigSnapshot(accepted=12, generation=gen)
    acc.apply_snapshot(late, gen)
    displays.append(acc.display_accepted)

    gen2 = acc.next_generation()
    r2 = XmrigRunner(Path("xmrig.exe"), host="h", port=1, username="u", generation=gen2)
    acc.apply_snapshot(XmrigSnapshot(accepted=0, generation=gen2), gen2)
    displays.append(acc.display_accepted)

    assert displays == [10, 12, 12, 12]
    assert 22 not in displays


def test_rigel_same_race_pattern():
    acc = ManagedShareAccum()
    gen = acc.next_generation()
    displays = []
    acc.apply_snapshot(RigelSnapshot(accepted=10, generation=gen), gen)
    displays.append(acc.display_accepted)
    acc.retire_with_final(gen, RigelSnapshot(accepted=12, generation=gen))
    displays.append(acc.display_accepted)
    acc.apply_snapshot(RigelSnapshot(accepted=12, generation=gen), gen)
    displays.append(acc.display_accepted)
    gen2 = acc.next_generation()
    acc.apply_snapshot(RigelSnapshot(accepted=0, generation=gen2), gen2)
    displays.append(acc.display_accepted)
    assert displays == [10, 12, 12, 12]


def test_double_retire_no_double_fold():
    acc = ManagedShareAccum()
    gen = acc.next_generation()
    acc.apply_snapshot(_Snap(accepted=5), gen)
    assert acc.retire_with_final(gen, _Snap(accepted=5))
    assert acc.retire_with_final(gen, _Snap(accepted=5)) is False
    assert acc.display_accepted == 5


def test_donation_and_thermal_fold_keeps_user_fee():
    acc = ManagedShareAccum()
    gen = acc.next_generation()
    acc.apply_snapshot(_Snap(accepted=8, engine_fee_shares=2, unattributed_shares=1, rejected=3), gen)
    assert acc.retire_with_final(gen, _Snap(accepted=8, engine_fee_shares=2, unattributed_shares=1, rejected=3))
    assert acc.display_accepted == 8
    assert acc.display_fee == 2
    assert acc.display_unattr == 1
    assert acc.display_rejected == 3
    # Termal afreandrsei new engine
    gen2 = acc.next_generation()
    acc.apply_snapshot(_Snap(accepted=0), gen2)
    assert acc.display_accepted == 8
    # Bnetworkis dilimi
    acc.set_donation_active(True)
    acc.apply_snapshot(_Snap(accepted=2), gen2)
    assert acc.display_accepted == 8
    assert acc.display_donation == 2
    assert acc.retire_with_final(gen2, _Snap(accepted=2))
    assert acc.display_donation == 2
    assert acc.display_accepted == 8


def test_rejected_survives_restart_fold():
    acc = ManagedShareAccum()
    gen = acc.next_generation()
    acc.apply_snapshot(_Snap(accepted=5, rejected=4), gen)
    acc.retire_with_final(gen, _Snap(accepted=5, rejected=4))
    gen2 = acc.next_generation()
    acc.apply_snapshot(_Snap(accepted=0, rejected=0), gen2)
    assert acc.display_rejected == 4
    assert acc.display_accepted == 5


def test_concurrent_stop_and_halt_fold_no_double():
    """stop() and miner-thread _halt_* same anda fold etse eandn 12 kalir."""
    import threading

    acc = ManagedShareAccum()
    gen = acc.next_generation()
    acc.apply_snapshot(_Snap(accepted=12), gen)
    barrier = threading.Barrier(2)
    results: list[bool] = []

    def retire():
        barrier.wait()
        results.append(acc.retire_with_final(gen, _Snap(accepted=12)))

    t1 = threading.Thread(target=retire)
    t2 = threading.Thread(target=retire)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert results.count(True) == 1
    assert results.count(False) == 1
    assert acc.display_accepted == 12
