"""Checks the live Stratum + GPU status of the running SoloBlockStrike instance."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    print("=== Live status (external observation) ===")
    print("Note: UI counters are inaccessible; evidenced by TCP + nvidia-smi.\n")

    # Python main.py
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -like '*SoloBlockStrike*main.py*' } | "
                "Select-Object -ExpandProperty ProcessId",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=30,
        ).strip()
    except Exception as exc:
        print(f"process query error: {exc}")
        out = ""

    pids = [p.strip() for p in out.splitlines() if p.strip().isdigit()]
    if not pids:
        print("SoloBlockStrike main.py is not working.")
        return 1
    print(f"process: PID {', '.join(pids)}")

    # Port 3333
    try:
        net = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | "
                "Where-Object { $_.RemotePort -eq 3333 } | "
                "Select-Object OwningProcess,RemoteAddress,RemotePort | Format-List",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        print("Stratum TCP 3333:")
        print(net.strip() or "No Connection")
        live_stratum = any(pid in net for pid in pids) and "3333" in net
    except Exception as exc:
        print(f"TCP query error: {exc}")
        live_stratum = False

    # GPU
    try:
        apps = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_gpu_memory",
                "--format=csv",
            ],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        util = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,temperature.gpu",
                "--format=csv",
            ],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        print("nvidia-smi compute apps:")
        print(apps.strip())
        print(util.strip())
        on_gpu = any(pid in apps for pid in pids)
    except Exception as exc:
        print(f"nvidia-smi error: {exc}")
        on_gpu = False

    print()
    if live_stratum:
        print("[OK] There is a live Stratum connection (ckpool :3333).")
    else:
        print("[!] No Stratum TCP — not connected to the pool or not connected yet.")
    if on_gpu:
        print("[OK] The process is in the GPU compute list (an OpenCL job may be running).")
    else:
        print(
            "[!] PID does not appear in the GPU compute list"
            "(low intensity / moment of sleep / authority); this alone does not mean there is no hash."
        )
    print(
        "\nFor counter increment: pytest tests/test_live_mining.py"
        "veya uygulamada 'Toplam deneme' / 'Son kernel'."
    )
    return 0 if live_stratum else 2


if __name__ == "__main__":
    raise SystemExit(main())
