"""Compare GpuMiner.search throughput with track_best off vs on. No network."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpu.miner import GpuMiner  # noqa: E402
from mining.bitcoin import bits_to_target, midstate_from_header  # noqa: E402

GENESIS = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000"
    "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
    "4b1e5e4a29ab5f49ffff001d1dac2b7c"
)


def run(miner: GpuMiner, track: bool, batch: int, rounds: int) -> float:
    ms = midstate_from_header(GENESIS)
    tgt = bits_to_target("1d00ffff")
    miner.search(ms, GENESIS, tgt, 0, batch, track_best=track)  # warm-up
    t0 = time.perf_counter()
    n = 0
    for i in range(rounds):
        n += miner.search(ms, GENESIS, tgt, (i * batch) & 0xFFFFFFFF, batch, track_best=track).scanned
    return n / (time.perf_counter() - t0) / 1e6


def main() -> int:
    batch = int(sys.argv[1]) if len(sys.argv) > 1 else 4_000_000
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    miner = GpuMiner()
    print(f"device={miner.device_name} batch={batch:,} rounds={rounds}")
    for rep in range(3):
        off = run(miner, False, batch, rounds)
        on = run(miner, True, batch, rounds)
        print(f"rep{rep}: off={off:.2f} MH/s  on={on:.2f} MH/s  delta={(on / off - 1) * 100:+.1f}%")
    miner.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
