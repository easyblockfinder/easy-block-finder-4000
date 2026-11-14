"""Bitcoin mining andrification report.

Kategoriler:
  - local account verified
  - sunucu share kabul etti
  - not yet verified

Counreandrse / GPU usage alone are not proof."""

from __future__ import annotations

import json
import random
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gpu.miner import GpuMiner, GpuUnavailableError  # noqa: E402
from mining.bitcoin import (  # noqa: E402
    bits_to_target,
    header_hash,
    is_hash_below_target,
    midstate_from_header,
    share_target_from_difficulty,
    validate_bitcoin_address,
)
from mining.job import job_from_notify  # noqa: E402
from stratum.client import DEFAULT_HOST, DEFAULT_PORT, StratumClient  # noqa: E402
from ui.settings_store import load_settings  # noqa: E402

GENESIS = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000"
    "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
    "4b1e5e4a29ab5f49ffff001d1dac2b7c"
)
GENESIS_HASH = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"

REPORT: dict[str, list[str]] = {
    "local account verified": [],
    "sunucu share kabul etti": [],
    "not yet verified": [],
}


def add(cat: str, msg: str) -> None:
    REPORT[cat].append(msg)
    print(f"[{cat}] {msg}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def test_known_header(gpu: GpuMiner) -> None:
    section("1) Bilinen genesis header — CPU + OpenCL")
    cpu = header_hash(GENESIS)
    cpu_be = cpu[::-1].hex()
    if cpu_be != GENESIS_HASH:
        add("not yet verified", f"CPU genesis hash did not match: {cpu_be}")
        return
    add("local account verified", f"CPU genesis hash = {GENESIS_HASH}")

    ms = midstate_from_header(GENESIS)
    nonce = struct.unpack("<I", GENESIS[76:80])[0]
    digests = gpu.hash_nonces(ms, GENESIS, [nonce])
    if len(digests) != 1:
        add("not yet verified", "GPU did not output for hash_nonces genesis")
        return
    gpu_be = digests[0][::-1].hex()
    if digests[0] != cpu:
        add(
            "not yet verified",
            f"GPU≠CPU genesis: gpu={gpu_be} cpu={cpu_be}",
        )
        return
    add("local account verified", f"OpenCL genesis hash GPU'dan okundu = {gpu_be}")

    net = bits_to_target("1d00ffff")
    if not is_hash_below_target(cpu, net):
        add("not yet verified", "Genesis does not meet the network target (unexpected)")
    else:
        add("local account verified", "Genesis target comparison (nBits) OK")


def test_live_job_100_nonces(gpu: GpuMiner, address: str) -> None:
    section("2) Live CKPool job — ≥100 random nonce GPU vs CPU")
    if not address:
        add("not yet verified", "No registered recipient address — live comparison skipped")
        return

    job_holder: dict = {}
    diff_holder: dict = {"diff": None}
    err_holder: dict = {}
    ready = threading.Event()

    def on_job(params, clean):
        job_holder["params"] = params
        job_holder["clean"] = clean
        ready.set()

    def on_diff(d):
        diff_holder["diff"] = d

    def on_status(s):
        if "hata" in s.lower() or "Hata" in s:
            err_holder["status"] = s

    client = StratumClient(
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        on_job=on_job,
        on_difficulty=on_diff,
        on_status=on_status,
        suggest_difficulty=1.0,
    )
    try:
        client.start(address)
        if not ready.wait(25):
            add(
                "not yet verified",
                f"mining.notify not received within 25s ({err_holder.get('status', 'timeout')})",
            )
            return
        # Short wait for set_difficulty
        time.sleep(2)
        server_diff = client.server_set_difficulty
        if server_diff is None:
            add(
                "not yet verified",
                "mining.set_difficulty has not been seen yet; job difficulty may be the client default",
            )
            use_diff = client.difficulty
        else:
            use_diff = server_diff
            add(
                "local account verified",
                f"Server mining.set_difficulty={server_diff} (suggest=1 sent;"
                f"local target not fitted)",
            )

        params = job_holder["params"]
        job = job_from_notify(
            params,
            client.extranonce1,
            client.extranonce2_size,
            float(use_diff),
            generation=1,
        )
        header0 = job.header_for_nonce(0)
        ms = job._midstate
        assert len(header0) == 80

        # Nonce/extranonce recheck — consecutive intervals
        ranges = []
        for _ in range(5):
            ranges.append(job.advance_nonce_range(1000))
        starts = [s for s, t in ranges]
        if starts != sorted(starts) or len(set(starts)) != len(starts):
            add("not yet verified", f"Suspicion of nonce range repetition: {ranges}")
        else:
            add("local account verified", f"Nonce ranges increasing/discrete: {ranges}")

        # Job transition: new notify → old revoke
        job.revoked = True
        if job.verify_candidate(0) is not None:
            add("not yet verified", "The revoked job still returned verify_candidate")
        else:
            add("local account verified", "Revoked job is being discarded")

        # Rework (simulated with the same parameters)
        job2 = job_from_notify(
            params,
            client.extranonce1,
            client.extranonce2_size,
            float(use_diff),
            generation=2,
        )
        header = job2.header_for_nonce(0)
        ms = job2._midstate

        rng = random.Random(0xB17C)
        nonces = [rng.randrange(0, 0xFFFFFFFF) for _ in range(100)]
        # GPU actual output
        gpu_digests = gpu.hash_nonces(ms, header, nonces)
        if len(gpu_digests) != 100:
            add("not yet verified", f"GPU returned {len(gpu_digests)}/100 digests")
            return

        share_t = share_target_from_difficulty(float(use_diff))
        net_t = bits_to_target(job2.nbits)
        mismatches = 0
        target_mismatch = 0
        for i, nonce in enumerate(nonces):
            hdr = job2.header_for_nonce(nonce)
            cpu_d = header_hash(hdr)
            gpu_d = gpu_digests[i]
            if cpu_d != gpu_d:
                mismatches += 1
                if mismatches <= 3:
                    add(
                        "not yet verified",
                        f"nonce={nonce:08x} CPU={cpu_d.hex()} GPU={gpu_d.hex()}",
                    )
            cpu_share = is_hash_below_target(cpu_d, share_t)
            gpu_share = is_hash_below_target(gpu_d, share_t)
            if cpu_share != gpu_share:
                target_mismatch += 1
            # byte order: BE image
            if cpu_d[::-1].hex() != gpu_d[::-1].hex() and cpu_d == gpu_d:
                pass  # The same.

        if mismatches == 0 and target_mismatch == 0:
            add(
                "local account verified",
                f"100 rastgele nonce: GPU digest == CPU SHA-256d; "
                f"share/network target comparison compliant (diff={use_diff})",
            )
        else:
            add(
                "not yet verified",
                f"Mismatch: hash={mismatches} target={target_mismatch}/100",
            )

        # Billing address = Authorize.net username
        if client.address == address and client.authorized:
            add(
                "local account verified",
                f"Authorize worker = recipient address ({address[:16]}…)."
                f"The Solo CKPool reward is linked to this user's name; the coinbase script is separate."
                f"It is produced by the pool.",
            )
        else:
            add("not yet verified", "The Authorize address does not match")

    except Exception as exc:
        add("not yet verified", f"Live Stratum error: {exc}")
    finally:
        client.stop()
        time.sleep(0.3)


def test_submit_logging_and_accept(address: str) -> None:
    section("3–4) suggest_difficulty + mining.submit id mapping")
    if not address:
        add("not yet verified", "No address — submit test skipped")
        return

    job_ev = threading.Event()
    submit_ev = threading.Event()
    state: dict = {"diff": None, "submit_ok": None, "meta": None}

    def on_job(p, c):
        state["job"] = p
        job_ev.set()

    def on_diff(d):
        state["diff"] = d

    def on_submit(ok, msg, meta):
        state["submit_ok"] = ok
        state["meta"] = meta
        submit_ev.set()

    client = StratumClient(
        suggest_difficulty=1.0,
        on_job=on_job,
        on_difficulty=on_diff,
        on_submit_result=on_submit,
    )
    try:
        client.start(address)
        if not job_ev.wait(25):
            add("not yet verified", "No job received for the submit test")
            return
        time.sleep(1.5)
        if client.server_set_difficulty is not None:
            add(
                "local account verified",
                f"set_difficulty sunucudan: {client.server_set_difficulty}",
            )
        else:
            add("not yet verified", "set_difficulty was not seen in this session")

        # Deliberate invalid submit — to see the server response with ID
        # (accepted is not expected; protocol log is verified)
        job = state["job"]
        req_id = client.submit_share(
            address,
            job[0],
            "00000000",
            job[7],
            "deadbeef",
            expected_session_id=client.session_id,
        )
        if not submit_ev.wait(20):
            add("not yet verified", f"No response for submit id={req_id}")
            return
        meta = state["meta"] or {}
        if meta.get("id") != req_id:
            add("not yet verified", f"Response ID did not match: {meta.get('id')} vs {req_id}")
        else:
            add(
                "local account verified",
                f"mining.submit id={req_id} request/response matched:"
                f"ok={state['submit_ok']} resp={meta.get('response')}",
            )
        # Invalid share should not be accepted
        if state["submit_ok"] is True:
            add(
                "not yet verified",
                "Invalid deadbeef share accepted returned (unexpected)",
            )
        else:
            add(
                "local account verified",
                "The server condition result==True is maintained for the increase in the Accepted counter."
                f"(bu denemede ok={state['submit_ok']})",
            )

        # Fact accepted: Scanning the share target with GPU — limited time
        section("4b) Real accepted share test (GPU, time-limited)")
        if client.server_set_difficulty is None:
            add(
                "not yet verified",
                "Server diff unknown — accepted share search skipped",
            )
            return
        diff = float(client.server_set_difficulty)
        job = job_from_notify(
            state["job"],
            client.extranonce1,
            client.extranonce2_size,
            diff,
            1,
        )
        share_t = job.share_target()
        found = None
        try:
            gpu2 = GpuMiner(autotune_local=False)
        except GpuUnavailableError as exc:
            add("not yet verified", f"No GPU for Accepted search: {exc}")
            return
        t0 = time.time()
        scanned = 0
        # ~20s / several million attempts — even diff=1 requires an average of ~2^32 hashes; it may not be found
        while time.time() - t0 < 20 and found is None:
            start, take = job.advance_nonce_range(2_000_000)
            if take <= 0:
                break
            res = gpu2.search(
                job._midstate,
                job.header_for_nonce(start),
                share_t,
                start,
                take,
                max_hits=8,
            )
            scanned += res.scanned
            for n in res.hits:
                # Verify CPU independence (GPU candidate)
                hdr = job.header_for_nonce(n)
                if is_hash_below_target(header_hash(hdr), share_t):
                    found = n
                    break
        gpu2.close()
        if found is None:
            add(
                "not yet verified",
                f"20s / {scanned:,} GPU is below the share target (diff={diff}) in the test"
                f"No nonce — the server could not be proven to have accepted this run."
                f"For diff=1, an average of ~4e9 hashes is required; this short test may be insufficient.",
            )
            return

        submit_ev.clear()
        state["submit_ok"] = None
        rid = client.submit_share(
            address,
            job.job_id,
            job.extranonce2_hex(),
            job.ntime,
            f"{found:08x}",
            expected_session_id=client.session_id,
        )
        if not submit_ev.wait(20):
            add("not yet verified", f"No valid share submit id={rid} response")
            return
        # Local evidence
        proof_hdr = job.header_for_nonce(found)
        proof_hash = header_hash(proof_hdr)
        add(
            "local account verified",
            f"Submit candidate nonce={found:08x} en2={job.extranonce2_hex()}"
            f"hash_be={proof_hash[::-1].hex()} "
            f"meets_share={is_hash_below_target(proof_hash, share_t)} "
            f"(server destination is verified separately)",
        )
        if state["submit_ok"] is True:
            add(
                "sunucu share kabul etti",
                f"mining.submit id={rid} result=true nonce={found:08x} diff={diff}",
            )
        else:
            add(
                "not yet verified",
                f"Lokal share hedefi OK; sunucu reddetti id={rid} "
                f"(Above target / stale job / pool mindiff olabilir). "
                f"resp={state['meta']}. "
                f"This does not invalidate the local SHA-256d accuracy; server acceptance is a separate category.",
            )
    except Exception as exc:
        add("not yet verified", f"Submit test hata: {exc}")
    finally:
        client.stop()


def test_ckpool_stats_link(address: str) -> None:
    section("5) CKPool user statistics URL")
    if not address:
        add("not yet verified", "Adres yok — istatistik linki yok")
        return
    url = f"https://raw.stats.ckpool.org/users/{address}"
    raw = f"http://raw.stats.ckpool.org/users/{address}"
    add(
        "local account verified",
        f"Kontrol linki: {url} (ve {raw}). Sunucu istatistikleri gecikebilir; "
        f"May not be visible with low hashrate / high mindiff.",
    )
    fetched = False
    last_err: Exception | None = None
    for candidate in (raw,):
        try:
            req = urllib.request.Request(
                candidate, headers={"User-Agent": "SoloBlockStrike-verify/0.1"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read(800).decode("utf-8", "replace")
            add(
                "local account verified",
                f"Statistics HTTP {resp.status} ({candidate}): {body[:160]!r}…",
            )
            fetched = True
            break
        except urllib.error.HTTPError as exc:
            add(
                "not yet verified",
                f"Statistics HTTP {exc.code} — no shares yet or delay"
                f"(normal olabilir): {candidate}",
            )
            fetched = True
            break
        except Exception as exc:
            last_err = exc
            continue
    if not fetched:
        add(
            "not yet verified",
            f"Automatic fetch of statistics failed: {last_err}."
            f"Check in your browser (there may be a delay): {url}",
        )


def main() -> int:
    print("SoloBlockStrike — mining verification")
    print("Temperature limits are maintained in practice; this script is a short network/GPU test.\n")

    cfg = load_settings()
    address = (cfg.get("address") or "").strip()
    ok, err = validate_bitcoin_address(address) if address else (False, "empty")
    if address and not ok:
        add("not yet verified", f"Registered address is invalid: {err}")
        address = ""
    print(f"Address: {address or '(none — limited to live tests)'}")

    try:
        gpu = GpuMiner(autotune_local=False)
    except GpuUnavailableError as exc:
        add("not yet verified", f"Failed to open OpenCL: {exc}")
        gpu = None

    if gpu:
        test_known_header(gpu)
        test_live_job_100_nonces(gpu, address)
        gpu.close()
    else:
        add("not yet verified", "No GPU — OpenCL tests could not be run")

    test_submit_logging_and_accept(address)
    test_ckpool_stats_link(address)

    section("ABSTRACT&#10;&#10;")
    for cat, items in REPORT.items():
        print(f"\n## {cat} ({len(items)})")
        for m in items:
            print(f"  - {m}")

    out = ROOT / "verification_report.json"
    out.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
