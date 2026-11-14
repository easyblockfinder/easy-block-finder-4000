"""Short OpenCL GPU benchmark + CPU verification. No Stratum/connection."""

from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gpu.miner import LOCAL_SIZE, GpuMiner  # noqa: E402
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
PAUSE_C = 80


def main() -> int:
    temp = GpuTemperatureMonitor()
    t = temp.read_celsius()
    print("=== SoloBlockStrike GPU benchmark (OpenCL) ===")
    print(f"Temperature: {t if t is not None else 'unreadable'}°C (pause ≥{PAUSE_C}°C)")
    if t is not None and t >= PAUSE_C:
        print("Too hot — benchmark canceled.")
        return 1

    miner = GpuMiner()
    print(f"Cihaz: {miner.device_name}")
    ms = midstate_from_header(GENESIS)
    net = bits_to_target("1d00ffff")

    # CPU ↔ GPU
    nonce = struct.unpack("<I", GENESIS[76:80])[0]
    res = miner.search(ms, GENESIS, net, nonce, 1)
    hdr = GENESIS[:76] + struct.pack("<I", nonce)
    cpu_ok = verify_header_against_targets(hdr, net, net)["meets_network"]
    print(f"CPU/GPU genesis: gpu_hits={res.hits} cpu_network={cpu_ok} scanned={res.scanned}")
    if res.hits != [nonce] or not cpu_ok:
        print("VERIFICATION FAILED")
        miner.close()
        return 1
    print("CPU ↔ GPU: matched")

    print("\n--- Old intensity 1 simulation (256 nonces + 50ms sleep) ---")
    old_batch, old_sleep = 256, 0.05
    rounds = 20
    t0 = time.perf_counter()
    scanned = 0
    for i in range(rounds):
        if temp.read_celsius() and temp.read_celsius() >= PAUSE_C:
            print("Pause heat")
            break
        r = miner.search(ms, GENESIS, net, i * old_batch, old_batch)
        scanned += r.scanned
        time.sleep(old_sleep)
    dt = time.perf_counter() - t0
    print(
        f"scanned={scanned:,}  time={dt:.2f}s"
        f"H/s={scanned/dt:,.0f}  ({scanned/dt/1e3:.2f} kH/s)  "
        f"global≈{((old_batch+LOCAL_SIZE-1)//LOCAL_SIZE)*LOCAL_SIZE} local={LOCAL_SIZE}"
    )

    print("\n--- New intensity 1 (batch+sleep, heat-protected) ---")
    batch, sleep_s = _INTENSITY[1]
    rounds = 8
    t0 = time.perf_counter()
    scanned = 0
    last = None
    for i in range(rounds):
        tc = temp.read_celsius()
        if tc is not None and tc >= PAUSE_C:
            print(f"Pause heating ({tc}°C)")
            break
        r = miner.search(ms, GENESIS, net, (i * batch) & 0xFFFFFFFF, batch)
        scanned += r.scanned
        last = r
        time.sleep(sleep_s)
    dt = time.perf_counter() - t0
    print(
        f"batch={batch:,} sleep={sleep_s*1000:.0f}ms  "
        f"scanned={scanned:,}  time={dt:.2f}s"
    )
    print(
        f"H/s={scanned/dt:,.0f}  ({scanned/dt/1e6:.2f} MH/s)  "
        f"global={last.global_size if last else 0:,} local={LOCAL_SIZE}"
    )

    print("\n--- Saf kernel (uyku yok, 2M nonce) ---")
    n = 2_000_000
    t0 = time.perf_counter()
    r = miner.search(ms, GENESIS, net, 0, n)
    dt = time.perf_counter() - t0
    print(
        f"scanned={r.scanned:,}  kernel={dt*1000:.1f}ms  "
        f"{r.scanned/dt/1e6:.2f} MH/s  global={r.global_size:,} local={r.local_size}"
    )

    miner.close()
    temp.close()
    print("\nNote: Connection/job acquisition is not included in this benchmark; only GPU hash.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
