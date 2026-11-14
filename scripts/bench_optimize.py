"""Before/after wall clock H/s + accuracy + temperature (no CUDA)."""

from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gpu.miner import GpuMiner  # noqa: E402
from mining.bitcoin import (  # noqa: E402
    bits_to_target,
    midstate_from_header,
    verify_header_against_targets,
)
from monitor.temp import GpuTemperatureMonitor  # noqa: E402
from worker.controller import _INTENSITY  # noqa: E402

GENESIS = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000"
    "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
    "4b1e5e4a29ab5f49ffff001d1dac2b7c"
)


def wall_loop(miner, ms, header, target, batch, sleep_s, rounds) -> tuple[int, float]:
    t0 = time.perf_counter()
    scanned = 0
    for i in range(rounds):
        r = miner.search(ms, header, target, (i * batch) & 0xFFFFFFFF, batch)
        scanned += r.scanned
        if sleep_s > 0:
            time.sleep(sleep_s)
    return scanned, time.perf_counter() - t0


def main() -> int:
    temp = GpuTemperatureMonitor()
    t_before = temp.read_celsius()
    print("=== Optimize verification / profile ===")
    print(f"Temperature before: {t_before}°C")

    miner = GpuMiner(autotune_local=True)
    print(f"Cihaz: {miner.device_name}  local_size={miner.local_size}")
    ms = midstate_from_header(GENESIS)
    net = bits_to_target("1d00ffff")

    nonce = struct.unpack("<I", GENESIS[76:80])[0]
    r = miner.search(ms, GENESIS, net, nonce, 1)
    cpu = verify_header_against_targets(
        GENESIS[:76] + struct.pack("<I", nonce), net, net
    )
    ok = r.hits == [nonce] and cpu["meets_network"]
    print(f"Accuracy genesis: {'OK' if ok else 'FAIL'} hits={r.hits}")

    # Previous cycle (for report)
    old_batch, old_sleep = 262_144, 0.04
    sc, dt = wall_loop(miner, ms, GENESIS, net, old_batch, old_sleep, 8)
    print(
        f"BEFORE (262144+40ms)x8: scanned={sc:,} wall={dt:.3f}s"
        f"{sc/dt/1e6:.2f} MH/s  temp={temp.read_celsius()}°C"
    )

    # New density 1
    batch, sleep_s = _INTENSITY[1]
    sc2, dt2 = wall_loop(miner, ms, GENESIS, net, batch, sleep_s, 8)
    print(
        f"SONRA intensity1 ({batch}+{sleep_s*1000:.0f}ms)x8: scanned={sc2:,} wall={dt2:.3f}s  "
        f"{sc2/dt2/1e6:.2f} MH/s  temp={temp.read_celsius()}°C"
    )

    # Saf 2M
    t0 = time.perf_counter()
    r3 = miner.search(ms, GENESIS, net, 0, 2_000_000)
    dt3 = time.perf_counter() - t0
    print(
        f"Saf kernel 2M: scanned={r3.scanned:,} {dt3*1000:.1f}ms  "
        f"{r3.scanned/dt3/1e6:.2f} MH/s  local={r3.local_size}"
    )

    # Random interval CPU matching (candidates)
    easy = (1 << 224) - 1  # relatively easy — may have a few hits
    r4 = miner.search(ms, GENESIS, easy, 0, 200_000)
    for n in r4.hits:
        hdr = GENESIS[:76] + struct.pack("<I", n)
        assert verify_header_against_targets(hdr, easy, net)["meets_share"], n
    print(f"CPU verification candidates: {len(r4.hits)} hits, all OK")

    print(f"Temperature after: {temp.read_celsius()}°C")
    print("Note: If the temperature cannot be read, the load is not automatically increased.")
    miner.close()
    temp.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
