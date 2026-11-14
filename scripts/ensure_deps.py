"""Check system requirements; uses OpenCL path. Does not install CUDA Toolkit."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning, module="pynvml")
warnings.filterwarnings("ignore", message=".*pynvml package is deprecated.*")

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "requirements.txt"
SRC = ROOT / "src"
MARKER = ROOT / ".deps_ok"

APPROX_MB = {
    "pyopencl": 0.7,
    "numpy": 15.0,
    "PyQt6": 60.0,
    "base58": 0.05,
    "bech32": 0.01,
    "nvidia-ml-py": 0.06,
    "pytest": 1.0,
}

OBSOLETE_CUDA_PIP = (
    "nvidia-cuda-nvrtc-cu12",
    "cuda-bindings",
    "cuda-core",
    "cuda-python",
    "pycuda",
)
OBSOLETE_WARN_PIP = ("pynvml",)


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    print(f"  [ERROR] {msg}")


def warn(msg: str) -> None:
    print(f"  [!] {msg}")


def info(msg: str) -> None:
    print(f"  · {msg}")


def run_pip(args: list[str]) -> int:
    cmd = [sys.executable, "-m", "pip", *args]
    print(f"  > {' '.join(cmd)}")
    return subprocess.call(cmd)


def check_python() -> bool:
    print("\n== Python ==")
    ver = sys.version_info
    ok(f"{sys.executable}")
    ok(f"Version {ver.major}.{ver.minor}.{ver.micro}")
    if ver.major < 3 or (ver.major == 3 and ver.minor < 10):
        fail("Python 3.10+ required: https://www.python.org/downloads/")
        return False
    return True


def remove_obsolete_cuda_packages() -> None:
    """Remove legacy CUDA / warning-spam pip packages."""
    try:
        import importlib.metadata as md
    except Exception:
        return

    to_remove: list[str] = []
    for name in (*OBSOLETE_CUDA_PIP, *OBSOLETE_WARN_PIP):
        try:
            md.version(name)
            to_remove.append(name)
        except Exception:
            pass
    if not to_remove:
        return

    print("\n== Legacy / unnecessary pip packages ==")
    warn(f"Removing: {', '.join(to_remove)}")
    run_pip(["uninstall", "-y", *to_remove])


def check_nvidia_opencl_driver() -> bool:
    print("\n== NVIDIA driver / OpenCL ==")
    smi = shutil.which("nvidia-smi")
    if not smi:
        fail("nvidia-smi not found. Install NVIDIA driver: https://www.nvidia.com/Download/index.aspx")
        return False
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=30,
        ).strip()
        ok(out)
    except Exception as exc:
        fail(f"nvidia-smi failed: {exc}")
        return False

    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    ocl = windir / "System32" / "OpenCL.dll"
    if not ocl.is_file():
        fail("OpenCL.dll not found. Reinstall NVIDIA driver with OpenCL.")
        return False
    try:
        import ctypes

        ctypes.WinDLL("OpenCL.dll")
        ok("OpenCL.dll OK")
    except Exception as exc:
        fail(f"OpenCL.dll load failed: {exc}")
        return False
    return True


def _need_install(mod: str) -> bool:
    try:
        importlib.import_module(mod)
        return False
    except Exception:
        return True


def _keccak_importable() -> bool:
    for name in ("Crypto.Hash.keccak", "Cryptodome.Hash.keccak"):
        try:
            importlib.import_module(name)
            return True
        except Exception:
            continue
    return False


def ensure_keccak() -> bool:
    """
    Real Keccak-256 for Monero address checksum (no SHA3 fallback).
    Triggers pycryptodome install if missing, then re-verifies.
    """
    print("\n== Keccak (pycryptodome) ==")
    if _keccak_importable():
        ok("Crypto.Hash.keccak")
        return True
    warn("missing: pycryptodome (Crypto.Hash.keccak) — required for XMR address validation")
    code = run_pip(["install", "pycryptodome>=3.20"])
    if code != 0:
        fail("pycryptodome install failed.")
        info(f'Manual: "{sys.executable}" -m pip install "pycryptodome>=3.20"')
        return False
    for key in list(sys.modules):
        if key == "Crypto" or key.startswith("Crypto.") or key.startswith("Cryptodome"):
            del sys.modules[key]
    if not _keccak_importable():
        fail(
            "pycryptodome installed but Crypto.Hash.keccak still missing. "
            "SHA3-256 fallback is not used — XMR checksum would be unsafe."
        )
        return False
    ok("Crypto.Hash.keccak installed")
    return True


def ensure_pip_packages() -> bool:
    print("\n== Python packages ==")
    if not REQ.is_file():
        fail(f"requirements.txt not found: {REQ}")
        return False

    required = [
        ("PyQt6", "PyQt6"),
        ("numpy", "numpy"),
        ("base58", "base58"),
        ("bech32", "bech32"),
        ("pynvml", "nvidia-ml-py"),
        ("pyopencl", "pyopencl"),
        ("qrcode", "qrcode"),
    ]
    missing_pips: list[str] = []
    for mod, pip_name in required:
        if _need_install(mod):
            warn(f"missing package: {pip_name}")
            missing_pips.append(pip_name)
        else:
            ok(mod)

    if missing_pips:
        approx = sum(APPROX_MB.get(p, 5.0) for p in missing_pips)
        if "PyQt6" in missing_pips:
            approx = max(approx, 70.0)
        warn(f"Download size about ~{approx:.0f} MB — CUDA Toolkit is not installed.")
        info(f"Will install: {', '.join(missing_pips)}")
        code = run_pip(["install", "-r", str(REQ)])
        if code != 0:
            fail("pip install failed.")
            info(f'Manual: "{sys.executable}" -m pip install -r "{REQ}"')
            return False
        for mod, pip_name in required:
            if _need_install(mod):
                fail(f"Still missing: {pip_name}")
                return False
            ok(f"{mod} installed")
    if not ensure_keccak():
        return False
    return True


def check_opencl_runtime() -> bool:
    print("\n== OpenCL GPU ==")
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    try:
        import pyopencl as cl
    except Exception as exc:
        fail(f"pyopencl not installed: {exc}")
        info('python -m pip install "pyopencl>=2024"')
        return False

    try:
        platforms = cl.get_platforms()
        if not platforms:
            fail("No OpenCL platform. Reinstall NVIDIA driver.")
            return False
        gpu_found = False
        for p in platforms:
            for d in p.get_devices():
                info(f"{p.name}: {d.name}")
                if "nvidia" in (d.vendor or "").lower() or "nvidia" in (d.name or "").lower():
                    gpu_found = True
        if not gpu_found:
            fail("No NVIDIA OpenCL GPU. No CPU/CUDA Toolkit fallback.")
            return False
    except Exception as exc:
        fail(f"OpenCL device list failed: {exc}")
        return False

    try:
        from gpu.miner import GpuMiner, GpuUnavailableError

        miner = GpuMiner()
        ok(f"Kernel ready — {miner.device_name}")
        miner.close()
    except GpuUnavailableError as exc:
        fail(str(exc))
        return False
    except Exception as exc:
        fail(f"OpenCL miner error: {exc}")
        return False
    return True


def check_nvml() -> bool:
    print("\n== GPU temperature ==")
    try:
        import pynvml

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        ok(f"{temp}°C")
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
    except Exception as exc:
        warn(f"Unreadable ({exc}) — thermal protection off, mining continues.")
    return True


def main() -> int:
    quiet = "--quiet" in sys.argv or "-q" in sys.argv
    force = "--force" in sys.argv
    cpu_only = "--cpu-only" in sys.argv or os.environ.get(
        "SOLOBLOCKSTRIKE_CPU_ONLY", ""
    ).strip() in ("1", "true", "yes")

    if quiet and MARKER.is_file() and not force:
        mode = MARKER.read_text(encoding="utf-8").strip().lower()
        if cpu_only or mode == "cpu-only":
            if _keccak_importable() and not _need_install("PyQt6"):
                print("Requirements: CPU-only already verified (XMR).")
                return 0
        else:
            windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
            if (
                (windir / "System32" / "OpenCL.dll").is_file()
                and not _need_install("pyopencl")
                and _keccak_importable()
            ):
                print("Requirements: already verified (quick check OK).")
                return 0

    print(
        "Easy Block Finder 4000 — requirement check"
        + (" (CPU-only / XMR)" if cpu_only else " (OpenCL)")
    )
    print(f"Project: {ROOT}")

    remove_obsolete_cuda_packages()

    if cpu_only:
        warn(
            "NVIDIA/OpenCL skipped — app will start; BTC/BCH/RVN/ERG "
            "GPU checks run at engine selection."
        )
        steps = [check_python, ensure_pip_packages]
    else:
        steps = [
            check_python,
            check_nvidia_opencl_driver,
            ensure_pip_packages,
            check_opencl_runtime,
            check_nvml,
        ]
    for step in steps:
        if not step():
            if MARKER.exists():
                try:
                    MARKER.unlink()
                except OSError:
                    pass
            print("\nSetup could not complete. Run start.bat again.")
            if not cpu_only:
                info("CPU-only XMR: start.bat cpu   or  ensure_deps.py --cpu-only")
            return 1

    try:
        MARKER.write_text("cpu-only\n" if cpu_only else "full\n", encoding="utf-8")
    except OSError:
        pass
    if cpu_only:
        print("\nCPU-only requirements ready (XMR). GPU networks verified separately.")
    else:
        print("\nAll required dependencies are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
