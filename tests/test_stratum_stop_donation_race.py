"""BTC stratum: stop∥donation transitioni — stop afreandrsei new stratum must not open."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from networks.profiles import get_profile  # noqa: E402
from worker.controller import MiningController  # noqa: E402


def test_stop_blocks_stratum_restart_during_donation_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    c._profile = get_profile("btc")
    c.network_id = "btc"
    c.address = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
    c._mining_address = c.address
    c._donation_active = False
    c._start_time = 0.0
    c.test_mode = False

    started = {"n": 0}
    fake = MagicMock()
    fake.stop = MagicMock()

    def fake_start_stratum(addr: str) -> None:
        with c._motor_ops:
            if c._motor_start_blocked():
                return
            started["n"] += 1
            c._stratum = fake

    c._start_stratum_for = fake_start_stratum  # type: ignore[method-assign]
    c._stratum = fake

    barrier = threading.Barrier(2)

    def donation_sync():
        barrier.wait()
        # stop bayraklari set edilmjob olabilir
        with c._motor_ops:
            if c._motor_start_blocked():
                return
            if c._stratum:
                c._stratum.stop()
                c._stratum = None
            c._donation_active = True
            c._start_stratum_for("bc1qdonationfake0000000000000000000000000")

    def user_stop():
        barrier.wait()
        c._stopping = True
        c._stop.set()
        with c._motor_ops:
            if c._stratum is not None:
                c._stratum.stop()
                c._stratum = None

    t1 = threading.Thread(target=donation_sync)
    t2 = threading.Thread(target=user_stop)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert started["n"] == 0
    assert c._stratum is None


def test_start_stratum_for_noops_when_stopping(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR", str(tmp_path))
    c = MiningController()
    c._profile = get_profile("btc")
    c._stopping = True
    c._stop.set()
    c._start_stratum_for("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    assert c._stratum is None
