"""Canli mining attemptleri: GPU kernel scan artiyor mu? (Stratum ≠ account)."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.bitcoin import midstate_from_header  # noqa: E402
from mining.job import MiningJob  # noqa: E402
from worker.controller import MiningController  # noqa: E402

GENESIS = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000"
    "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
    "4b1e5e4a29ab5f49ffff001d1dac2b7c"
)


def _probe_opencl_or_skip():
    """Donmomentm nonesa start beforesi gerekceli skip; application errorsini gizleme."""
    from gpu.miner import GpuMiner, GpuUnavailableError

    try:
        m = GpuMiner(autotune_local=False)
        name = m.device_name
        m.close()
        return name
    except GpuUnavailableError as exc:
        pytest.skip(f"OpenCL/NVIDIA yok: {exc}")


def test_live_gpu_scans_increase_total_hashes(isolated_controller):
    """
    Test modunda (pool none) controller real OpenCL scan yapsin.
    total_hashes and last_scanned artsin; this Stratum connectionsi not, hash attemptsidir.
    """
    _probe_opencl_or_skip()

    snapshots: list = []
    ready = threading.Event()

    def on_stats(s):
        snapshots.append(
            (
                s.total_hashes,
                s.last_scanned,
                s.hashrate,
                s.device_name,
                s.last_global,
                s.last_local,
                s.status,
            )
        )
        if s.total_hashes > 0 and s.last_scanned > 0:
            ready.set()

    ctrl = isolated_controller(on_stats=on_stats)
    ctrl.intensity = 1
    ctrl.start("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", test_mode=True)

    try:
        # Probe gectiyse status'ta "GPU" gecmesi skip gerekcesi not —
        # tarama nonesa application errorsi olarak assert.
        assert ready.wait(timeout=15), (
            "OpenCL vardi ama 15s forde GPU scan gorulmedi (application/kernel). "
            f"Son snapshot: {snapshots[-1] if snapshots else None}"
        )
        time.sleep(0.5)
        # Ikinci example — attemptler should increase
        t0 = snapshots[-1][0]
        deadline = time.time() + 8
        grew = False
        while time.time() < deadline:
            if snapshots[-1][0] > t0:
                grew = True
                break
            time.sleep(0.1)
        assert grew, f"total_hashes did not increase: {t0} → {snapshots[-1][0]}"

        total, scanned, rate, device, gsz, lsz, _status = snapshots[-1]
        assert "1650" in device or "NVIDIA" in device.upper() or device
        assert scanned > 0
        assert gsz >= scanned or gsz >= lsz  # global hizali
        assert lsz in (64, 128, 256, 512)
        assert total >= scanned
        # Yogunluk 1 with batch buyudu — en az a tarama
        assert total >= 1000, f"too few attempt: {total}"
        assert rate > 0
    finally:
        ctrl.stop()


def test_kernel_scanned_equals_requested_count():
    """Tek kernel cnetworkrheatnda scanned == istenen count (different nonce interval)."""
    from gpu.miner import GpuMiner, GpuUnavailableError

    try:
        gpu = GpuMiner(autotune_local=False)
    except GpuUnavailableError as exc:
        pytest.skip(str(exc))

    ms = midstate_from_header(GENESIS)
    easy = (1 << 256) - 1
    r1 = gpu.search(ms, GENESIS, easy, 0, 10_000)
    r2 = gpu.search(ms, GENESIS, easy, 10_000, 10_000)
    gpu.close()

    assert r1.scanned == 10_000
    assert r2.scanned == 10_000
    assert r1.start_nonce == 0
    assert r2.start_nonce == 10_000
    assert r1.global_size >= 10_000
    assert r2.global_size >= 10_000
    assert r1.start_nonce != r2.start_nonce


def test_job_nonce_ranges_do_not_repeat_unnecessarily():
    """advance_nonce_range same nonceleri gereksiz tekrarlamasin."""
    job = MiningJob(
        job_id="t",
        prevhash="0" * 64,
        coinb1="00",
        coinb2="00",
        merkle_branches=[],
        version="20000000",
        nbits="1d00ffff",
        ntime="5a000000",
        clean_jobs=True,
        extranonce1="00",
        extranonce2_size=4,
        difficulty=1.0,
    )
    job.rebuild_work()
    seen = []
    for _ in range(5):
        start, take = job.advance_nonce_range(1000)
        seen.append((start, take))
    assert seen[0] == (0, 1000)
    assert seen[1] == (1000, 1000)
    assert seen[2] == (2000, 1000)
    assert all(t == 1000 for _, t in seen)
