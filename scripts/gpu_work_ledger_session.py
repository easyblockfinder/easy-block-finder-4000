"""
REAL GPU mining session with Stratum Work Ledger (production kernel).

WARNING: Starts live BTC mining against the selected pool using the wallet
from local settings. Generates heat/load. Requires --confirm-real-gpu.

Uses MiningController + GpuMiner.search (no audit histogram required).
Exports measurement_source=gpu_completed_batches. Does not change nonce
allocation or the production sha256d.cl kernel.

Usage:
  runtime\\python.exe scripts\\gpu_work_ledger_session.py --minutes 35 --confirm-real-gpu
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audit.work_ledger import MEASUREMENT_GPU, mask_secret  # noqa: E402
from networks.pool_resolve import resolve_pool  # noqa: E402
from ui.settings_store import load_settings  # noqa: E402
from worker.controller import MiningController  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=35.0)
    ap.add_argument("--intensity", type=int, default=8)
    ap.add_argument(
        "--confirm-real-gpu",
        action="store_true",
        help="Required. Acknowledge this starts real GPU mining.",
    )
    ap.add_argument(
        "--out",
        default=str(ROOT / "dist" / "work_ledger_public_pool_GPU.json"),
    )
    args = ap.parse_args()
    if not args.confirm_real_gpu:
        print(
            "Refusing to start: pass --confirm-real-gpu to run a REAL GPU session "
            "(heat/load; uses settings wallet). For notify-only synthetic, use "
            "scripts/stratum_work_ledger_session.py instead."
        )
        return 2

    cfg = load_settings()
    addr = str((cfg.get("address_by_network") or {}).get("btc") or cfg.get("address") or "").strip()
    if not addr:
        print("No BTC address in settings — abort")
        return 2

    pool_by = cfg.get("pool_by_network") or {}
    # Prefer Public Pool preset for this diagnostic
    btc_sel = dict(pool_by.get("btc") or {})
    btc_sel["mode"] = "preset"
    btc_sel["preset_id"] = "public_pool_solo"
    pool_by = {**pool_by, "btc": btc_sel}
    ep = resolve_pool("btc", pool_by)

    last_stats = {"hashrate": 0.0, "status": "", "gpu_best": 0.0, "acc_best": 0.0}

    def on_stats(st) -> None:
        last_stats["hashrate"] = float(getattr(st, "hashrate", 0) or 0)
        last_stats["status"] = str(getattr(st, "status", "") or "")
        gb = getattr(st, "best_hash", None) or getattr(st, "gpu_best_difficulty", None)
        # MiningStats fields vary — keep soft
        for name in ("best_share_difficulty", "gpu_best_difficulty", "best_difficulty"):
            v = getattr(st, name, None)
            if v is not None:
                try:
                    last_stats["gpu_best"] = float(v)
                except (TypeError, ValueError):
                    pass

    ctrl = MiningController(on_stats=on_stats)
    ctrl.update_settings(int(args.intensity), pause_temp=85, resume_temp=75)
    ctrl.update_idle_options(enabled=False)
    # Ledger ON, Live Audit histogram OFF
    ctrl.set_work_ledger(True)
    ctrl.set_live_audit(False)

    print(
        f"REAL GPU session → {ep.host}:{ep.port} ({ep.display_name}) "
        f"as {mask_secret(addr)} for {args.minutes} min, intensity={args.intensity}",
        flush=True,
    )
    print(
        "measurement_source will be gpu_completed_batches; histogram audit OFF.",
        flush=True,
    )

    ctrl.start(
        addr,
        test_mode=False,
        network_id="btc",
        allow_mine_without_temp=True,
        pool_endpoint=ep,
        pool_by_network=pool_by,
    )

    t0 = time.time()
    deadline = t0 + max(60.0, float(args.minutes) * 60.0)
    last_print = 0.0
    try:
        while time.time() < deadline:
            time.sleep(2.0)
            if not ctrl.is_running():
                print("Controller stopped unexpectedly", flush=True)
                break
            now = time.time()
            if now - last_print >= 60.0:
                last_print = now
                m = ctrl.work_ledger_metrics() or {}
                print(
                    f"[{(now - t0) / 60:.1f}m] H/s={last_stats['hashrate']:.0f} "
                    f"attempts={m.get('total_attempts', 0)} "
                    f"dup%={m.get('duplicate_rate_percent', 0):.4f} "
                    f"identical={m.get('identical_work_notifications', 0)} "
                    f"notifies={m.get('notify_count', 0)} "
                    f"cut={m.get('jobs_cut_by_notify', 0)} "
                    f"overhead%={m.get('ledger_overhead_pct_of_kernel', 0):.4f} "
                    f"status={last_stats['status'][:60]}",
                    flush=True,
                )
    finally:
        try:
            ctrl.stop()
        except Exception as exc:
            print(f"stop error: {exc}", flush=True)
        # allow stop to settle
        time.sleep(2.0)

    report = ctrl.work_ledger_export(mask=True) or {}
    m = ctrl.work_ledger_metrics() or {}
    report["session_meta"] = {
        "mode": "REAL_GPU MiningController + production sha256d kernel",
        "measurement_source": MEASUREMENT_GPU,
        "host": ep.host,
        "port": ep.port,
        "pool": ep.display_name,
        "minutes_requested": args.minutes,
        "minutes_elapsed": (time.time() - t0) / 60.0,
        "intensity": int(args.intensity),
        "address_masked": mask_secret(addr),
        "histogram_audit": False,
        "final_hashrate": last_stats["hashrate"],
        "purpose": "Investigate whether duplicate nonce-space / identical work explains stalled GPU best (~4.2K)",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n=== REAL GPU SESSION SUMMARY ===", flush=True)
    for k in (
        "measurement_source",
        "attempts_are_gpu_completed",
        "attempts_are_synthetic",
        "total_attempts",
        "unique_attempts",
        "duplicate_attempts",
        "duplicate_rate_percent",
        "identical_work_notifications",
        "jobs_cut_by_notify",
        "hashes_completed_on_cut_jobs",
        "aborted_inflight_batches",
        "reconnects",
        "extranonce1_changes",
        "batches_completed",
        "notify_count",
        "ledger_overhead_pct_of_kernel",
        "hashrate_mean",
        "hashrate_max",
    ):
        print(f"{k}: {m.get(k)}", flush=True)
    gb = m.get("gpu_best_timeline") or []
    ab = m.get("accepted_best_timeline") or []
    print(f"gpu_best_events: {len(gb)} last={gb[-1] if gb else None}", flush=True)
    print(f"acc_best_events: {len(ab)} last={ab[-1] if ab else None}", flush=True)
    print(f"wrote {out}", flush=True)

    if not m.get("attempts_are_gpu_completed"):
        print("ERROR: export not marked as GPU completed", flush=True)
        return 4
    if int(m.get("batches_completed") or 0) < 1:
        print("ERROR: no GPU batches completed — session invalid", flush=True)
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
