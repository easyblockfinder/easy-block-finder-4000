"""Liand CKPool share acceptance attempt after Merkle fix.
Accepted is reported only when serandr result==True."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gpu.miner import GpuMiner, GpuUnavailableError  # noqa: E402
from mining.bitcoin import nonce_to_submit_hex  # noqa: E402
from mining.job import job_from_notify  # noqa: E402
from stratum.client import StratumClient  # noqa: E402
from ui.settings_store import load_settings  # noqa: E402


def main() -> int:
    address = (load_settings().get("address") or "").strip()
    if not address:
        print("SONUC: canli_test_yapilamadi — kayitli adres yok")
        return 2

    job_ev = threading.Event()
    submit_ev = threading.Event()
    state: dict = {"job": None, "diff": None, "submit": None, "job_seq": 0}
    lock = threading.Lock()

    def on_job(params, clean):
        with lock:
            state["job"] = params
            state["clean"] = clean
            state["job_seq"] = int(state["job_seq"]) + 1
        job_ev.set()

    def on_diff(d):
        with lock:
            state["diff"] = d

    def on_submit(ok, msg, meta):
        with lock:
            state["submit"] = {"ok": ok, "msg": msg, "meta": meta}
        submit_ev.set()

    client = StratumClient(
        on_job=on_job,
        on_difficulty=on_diff,
        on_submit_result=on_submit,
        on_status=lambda s: print(f"STATUS: {s}"),
        suggest_difficulty=1.0,
    )
    gpu = None
    try:
        gpu = GpuMiner(autotune_local=False)
        client.start(address)
        if not job_ev.wait(30):
            print("SONUC: canli_test_yapilamadi — mining.notify gelmedi")
            return 3
        time.sleep(1.0)
        for entry in reversed(client.wire_log[:20]):
            print(f"WIRE: {entry.get('kind')} { {k:v for k,v in entry.items() if k not in ('raw','kind')} }")

        diff = float(state["diff"] or client.difficulty or 1.0)
        print(
            f"SUBSCRIBE en1={client.extranonce1} en2_size={client.extranonce2_size} "
            f"diff={diff} job={state['job'][0]}"
        )

        job = job_from_notify(
            state["job"],
            client.extranonce1,
            client.extranonce2_size,
            diff,
            generation=1,
        )
        snap0 = job.snapshot()
        print(
            f"SNAPSHOT job={snap0.job_id} diff={snap0.difficulty} "
            f"en2={snap0.extranonce2_hex} ntime={snap0.ntime}"
        )

        deadline = time.time() + 120.0
        accepted = False
        attempts = 0
        last_seq = state["job_seq"]
        while time.time() < deadline and not accepted:
            with lock:
                seq = state["job_seq"]
                params = state["job"]
                cur_diff = float(state["diff"] or client.difficulty or diff)
            if seq != last_seq and params:
                job.revoked = True
                job = job_from_notify(
                    params,
                    client.extranonce1,
                    client.extranonce2_size,
                    cur_diff,
                    job.generation + 1,
                )
                last_seq = seq
                print(f"YENI_IS {job.job_id} diff={job.difficulty}")

            start, take = job.advance_nonce_range(2_097_152)
            if take <= 0:
                continue
            batch_snap = job.snapshot()
            res = gpu.search(
                midstate=job._midstate,
                header80=job.header_for_nonce(start),
                share_target=batch_snap.share_target(),
                start_nonce=start,
                count=take,
            )
            for nonce in res.hits:
                verified = job.verify_candidate(nonce, snapshot=batch_snap)
                if not verified:
                    print(f"HIT_DROP nonce={nonce:08x} (rebuild/target uyusmadi)")
                    continue
                attempts += 1
                submit_ev.clear()
                with lock:
                    state["submit"] = None
                nonce_hex = verified["nonce_hex"]
                print(
                    f"SUBMIT#{attempts} job={verified['job_id']} en2={verified['extranonce2']} "
                    f"ntime={verified['ntime']} nonce={nonce_hex} "
                    f"hash={verified['hash_be_hex']} diff={verified['difficulty']} "
                    f"merkle={verified['merkle_root_hex'][:16]}… "
                    f"header_match={verified['buffer_header_match']} "
                    f"nonce_id_ok={nonce_to_submit_hex(nonce)==nonce_hex}"
                )
                req = client.submit_share(
                    address,
                    verified["job_id"],
                    verified["extranonce2"],
                    verified["ntime"],
                    nonce_hex,
                    expected_session_id=client.session_id,
                )
                if not submit_ev.wait(20):
                    print(f"SUBMIT_TIMEOUT id={req}")
                    continue
                with lock:
                    sub = dict(state["submit"] or {})
                print(f"RESPONSE id={req} ok={sub.get('ok')} msg={sub.get('msg')} meta={sub.get('meta')}")
                if sub.get("ok") is True:
                    accepted = True
                    break

        print("WIRE_TAIL:")
        for entry in list(reversed(client.wire_log[:12])):
            print(f"  {entry}")

        if accepted:
            print("SONUC: sunucu_share_kabul_etti")
            return 0
        print(
            f"SONUC: henuz_dogrulanamadi — {attempts} gecerli submit, "
            f"90s icinde accepted yok (diff={diff})"
        )
        return 1
    except GpuUnavailableError as exc:
        print(f"SONUC: canli_test_yapilamadi — GPU: {exc}")
        return 4
    except Exception as exc:
        print(f"SONUC: canli_test_yapilamadi — {exc}")
        return 5
    finally:
        client.stop()
        if gpu:
            gpu.close()


if __name__ == "__main__":
    raise SystemExit(main())
