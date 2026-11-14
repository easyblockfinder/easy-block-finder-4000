from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.xmrig_runner import XmrigRunner, XmrigSnapshot  # noqa: E402
from mining.managed_counters import ManagedShareAccum  # noqa: E402
from worker.controller import MiningController  # noqa: E402


def test_controller_fold_before_clear_keeps_12(tmp_path, monkeypatch):
    """
    Uretim yolu: stop() fold → ref sil; late callback rejected; new gen 0 → 12.
    """
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    shares = ManagedShareAccum()
    c._share_accum = shares
    gen = shares.next_generation()
    c._motor_gen = gen

    r = XmrigRunner(Path("xmrig.exe"), host="h", port=1, username="u", generation=gen)
    r._user_accepted = 10
    r.snapshot = XmrigSnapshot(accepted=10, generation=gen)
    shares.apply_snapshot(r.snapshot, gen)
    assert c.stats.accepted == 0  # henuz push none
    c.stats.accepted = shares.display_accepted
    assert c.stats.accepted == 10

    displays = [shares.display_accepted]

    # stop ordersi: son snapshot 12, fold, after late callback
    r._user_accepted = 12
    r.snapshot = XmrigSnapshot(accepted=12, generation=gen)
    c._xmrig = r
    c._fold_active_motor_shares()
    displays.append(shares.display_accepted)
    assert displays[-1] == 12

    # UI stop ref sildi
    c._xmrig = None
    # Late callback (emekli gen)
    shares.apply_snapshot(XmrigSnapshot(accepted=14, generation=gen), gen)
    displays.append(shares.display_accepted)

    gen2 = shares.next_generation()
    c._motor_gen = gen2
    shares.apply_snapshot(XmrigSnapshot(accepted=0, generation=gen2), gen2)
    displays.append(shares.display_accepted)

    assert displays == [10, 12, 12, 12]
    assert 22 not in displays


def test_halt_when_ref_already_none_still_folds(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    shares = ManagedShareAccum()
    gen = shares.next_generation()
    shares.apply_snapshot(XmrigSnapshot(accepted=12, generation=gen), gen)
    c._retire_motor_into(shares, None, gen)
    assert shares.display_accepted == 12
    assert shares.apply_snapshot(XmrigSnapshot(accepted=99, generation=gen), gen) is False


def test_controller_stop_fold_then_late_callback(tmp_path, monkeypatch):
    """MiningController.stop() fold eder; stop ici late callback sayaci inflationz."""
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    shares = ManagedShareAccum()
    c._share_accum = shares
    gen = shares.next_generation()
    c._motor_gen = gen

    r = XmrigRunner(Path("xmrig.exe"), host="h", port=1, username="u", generation=gen)
    displays: list[int] = []

    r.on_snapshot = lambda snap: shares.apply_snapshot(snap, snap.generation)
    r._user_accepted = 10
    r.snapshot = XmrigSnapshot(accepted=10, generation=gen)
    shares.apply_snapshot(r.snapshot, gen)
    displays.append(shares.display_accepted)
    assert displays[-1] == 10

    # Son gecerli durum 12 (fold beforesi take_final thisnu alir)
    r._user_accepted = 12
    r.snapshot = XmrigSnapshot(accepted=12, generation=gen)
    c._xmrig = r
    c._fold_active_motor_shares()
    displays.append(shares.display_accepted)
    assert displays[-1] == 12

    # stop / late callback — emekli gen
    r.retire()
    shares.apply_snapshot(XmrigSnapshot(accepted=99, generation=gen), gen)
    displays.append(shares.display_accepted)

    gen2 = shares.next_generation()
    shares.apply_snapshot(XmrigSnapshot(accepted=0, generation=gen2), gen2)
    displays.append(shares.display_accepted)

    assert displays == [10, 12, 12, 12]
    assert 22 not in displays
