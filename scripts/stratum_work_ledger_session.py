"""
SYNTHETIC listen + time-budget Stratum Work Ledger session (NO GPU).

This script does NOT run production mining. Exports are labeled
measurement_source=synthetic_time_budget_not_gpu and must never be treated
as GPU ATTEMPTS proof.

For real GPU evidence use:
  scripts/gpu_work_ledger_session.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audit.work_ledger import (  # noqa: E402
    MEASUREMENT_SYNTHETIC,
    StratumWorkLedger,
    mask_secret,
)
from mining.job import job_from_notify  # noqa: E402
from stratum.client import StratumClient  # noqa: E402


def _load_btc_address() -> str:
    p = Path(os.environ.get("LOCALAPPDATA") or "") / "EasyBlockFinder4000" / "settings.json"
    if not p.is_file():
        return ""
    data = json.loads(p.read_text(encoding="utf-8"))
    return str((data.get("address_by_network") or {}).get("btc") or "").strip()


def _en2_hex(size: int) -> str:
    return (0).to_bytes(max(1, int(size)), "big").hex()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="public-pool.io")
    ap.add_argument("--port", type=int, default=3333)
    ap.add_argument("--minutes", type=float, default=25.0)
    ap.add_argument("--hps", type=float, default=200e6)
    ap.add_argument(
        "--out",
        default=str(ROOT / "dist" / "work_ledger_public_pool_SYNTHETIC.json"),
    )
    args = ap.parse_args()

    addr = _load_btc_address()
    if not addr:
        print("No BTC address in settings.json — abort")
        return 2

    worker = f"{addr}.ebfledger"
    ledger = StratumWorkLedger(measurement_source=MEASUREMENT_SYNTHETIC)
    lock = threading.Lock()
    state: dict = {
        "job": None,
        "job_started": 0.0,
        "notifies": 0,
        "generation": 0,
    }

    print(
        "WARNING: SYNTHETIC mode — not a GPU mining measurement. "
        "Use scripts/gpu_work_ledger_session.py for real ATTEMPTS.",
        flush=True,
    )

    def _close_job(now: float) -> None:
        job = state["job"]
        if job is None:
            return
        started = float(state["job_started"] or now)
        elapsed = max(0.0, now - started)
        scanned = int(elapsed * float(args.hps))
        if scanned <= 0:
            scanned = 1
        count = min(scanned, 0x100000000)
        ledger.on_gpu_batch_completed(
            job_id=str(job.job_id),
            work_family_id="",
            extranonce2_hex=_en2_hex(job.extranonce2_size),
            start_nonce=0,
            allocated_count=count,
            scanned=count,
        )
        if bool(getattr(job, "clean_jobs", True)):
            job.mark_invalidated()
        else:
            job.mark_superseded()

    def on_job(params: list, clean: bool) -> None:
        with lock:
            now = time.time()
            _close_job(now)
            assert client is not None
            state["generation"] = int(state["generation"]) + 1
            job = job_from_notify(
                params,
                client.extranonce1,
                client.extranonce2_size,
                float(client.difficulty or 1.0),
                int(state["generation"]),
            )
            job.clean_jobs = bool(clean)
            state["job"] = job
            state["job_started"] = now
            state["notifies"] = int(state["notifies"]) + 1
            ledger.on_subscribe(
                session_id=int(client.session_id),
                extranonce1=str(client.extranonce1),
                extranonce2_size=int(client.extranonce2_size),
            )
            ledger.on_notify(
                job, bool(clean), session_id=int(client.session_id), payout_address=addr
            )
            m = ledger.metrics()
            print(
                f"[notify] n={state['notifies']} job={job.job_id} clean={clean} "
                f"identical={m['identical_work_notifications']} "
                f"(SYNTHETIC attempts — not GPU)",
                flush=True,
            )

    client = StratumClient(
        host=args.host,
        port=int(args.port),
        on_job=on_job,
        on_difficulty=lambda d: print(f"[diff] {d}", flush=True),
        on_status=lambda t: print(f"[status] {t}", flush=True),
        suggest_difficulty=None,
        password="x",
    )

    print(
        f"Connecting {args.host}:{args.port} as {mask_secret(worker)} "
        f"for {args.minutes} min (SYNTHETIC hps={args.hps:.0f})…",
        flush=True,
    )
    client.start(worker)

    t0 = time.time()
    while time.time() - t0 < 60 and not client.authorized:
        time.sleep(0.2)
    if not client.authorized:
        print("Authorize timeout", flush=True)
        client.stop()
        return 3

    ledger.on_subscribe(
        session_id=int(client.session_id),
        extranonce1=str(client.extranonce1),
        extranonce2_size=int(client.extranonce2_size),
    )

    deadline = time.time() + max(0.1, float(args.minutes) * 60.0)
    try:
        while time.time() < deadline:
            time.sleep(1.0)
    finally:
        with lock:
            _close_job(time.time())
        try:
            client.stop()
        except Exception:
            pass

    report = ledger.export_dict(mask=True)
    m = ledger.metrics()
    n = int(m.get("notify_count") or 0)
    report["session_meta"] = {
        "host": args.host,
        "port": args.port,
        "minutes_requested": args.minutes,
        "assumed_hps": args.hps,
        "address_masked": mask_secret(addr),
        "notifies": n,
        "mode": "SYNTHETIC listen+time_budget — NOT GPU",
        "measurement_source": MEASUREMENT_SYNTHETIC,
        "warning": "Do not cite total_attempts as GPU ATTEMPTS.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n=== SYNTHETIC SESSION (NOT GPU) ===", flush=True)
    print(f"notify_count: {n}", flush=True)
    print(f"identical_work_notifications: {m.get('identical_work_notifications')}", flush=True)
    print(f"measurement_source: {m.get('measurement_source')}", flush=True)
    print(f"wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
