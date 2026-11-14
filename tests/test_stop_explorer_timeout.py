from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.block_store import ExplorerTracker  # noqa: E402
from worker.controller import MiningController  # noqa: E402


def test_explorer_timeout_does_not_lock_new_start(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    hold = threading.Event()

    def zombie():
        hold.wait()

    t = threading.Thread(target=zombie, daemon=True)
    c._explorer._thread = t
    c._explorer._stop.set()
    t.start()
    # stop: explorer join timeout → yeni tracker, stop True (miner yok)
    old = c._explorer
    ok = c.stop()
    assert ok is True
    assert c._stop_failed is False
    assert not c._explorer.is_running()
    assert old.on_update is None  # zombie callback kesildi
    assert c._explorer is not old
    # Yeni oturum engellenmemeli
    assert c.is_running() is False
    hold.set()
    t.join(timeout=2)


def test_refresh_before_retire_updates_final(tmp_path, monkeypatch):
    from engines.xmrig_runner import XmrigRunner, XmrigSnapshot
    from mining.managed_counters import ManagedShareAccum

    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    r = XmrigRunner(Path("x"), host="h", port=1, username="u", generation=1)
    r._user_accepted = 10
    r.snapshot = XmrigSnapshot(accepted=10, generation=1)

    def fake_refresh():
        r._user_accepted = 12
        r.snapshot = XmrigSnapshot(accepted=12, generation=1)

    r.refresh_snapshot = fake_refresh  # type: ignore[method-assign]
    shares = ManagedShareAccum()
    gen = shares.next_generation()
    shares.apply_snapshot(XmrigSnapshot(accepted=10, generation=gen), gen)
    c._retire_motor_into(shares, r, gen)
    assert shares.display_accepted == 12
