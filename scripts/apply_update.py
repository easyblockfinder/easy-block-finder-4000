"""
External updater — runs AFTER the UI process exits.

Does not disable antivirus. Does not touch %LOCALAPPDATA%\\EasyBlockFinder4000
settings, wallets, logs, or miners/.

Usage:
  python scripts/apply_update.py --job %LOCALAPPDATA%\\...\\update_job.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Skip replacing these relative paths inside the install tree
SKIP_NAMES = {".git", ".venv", "venv", "__pycache__", ".deps_ok"}


def _log(msg: str) -> None:
    try:
        log_dir = Path(os.environ.get("LOCALAPPDATA") or ".") / "EasyBlockFinder4000" / "updates"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "apply_update.log").open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg + "\n")
    except OSError:
        pass


def wait_for_pid(pid: int, timeout_s: float = 120.0) -> None:
    if pid <= 0:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            # Windows: OpenProcess would be better; os.kill(pid, 0) works on Unix.
            if sys.platform == "win32":
                import ctypes

                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = ctypes.windll.kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
                )
                if not handle:
                    return
                ctypes.windll.kernel32.CloseHandle(handle)
            else:
                os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.4)
    _log(f"WARN: timed out waiting for pid {pid}; continuing carefully")


def _copy_tree(src: Path, dst: Path) -> None:
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        dirs[:] = [d for d in dirs if d not in SKIP_NAMES and not d.startswith(".")]
        target_root = dst / rel
        target_root.mkdir(parents=True, exist_ok=True)
        for name in files:
            if name in SKIP_NAMES:
                continue
            s = Path(root) / name
            d = target_root / name
            shutil.copy2(s, d)


def backup_install(install_dir: Path, backup_dir: Path) -> None:
    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    for child in install_dir.iterdir():
        if child.name in SKIP_NAMES or child.name.startswith("."):
            continue
        # Never backup huge venv if present under a different name — already skipped
        dest = backup_dir / child.name
        if child.is_dir():
            shutil.copytree(child, dest, ignore=shutil.ignore_patterns(*SKIP_NAMES, "*.pyc"))
        else:
            shutil.copy2(child, dest)


def restore_backup(backup_dir: Path, install_dir: Path) -> None:
    if not backup_dir.is_dir():
        return
    for child in backup_dir.iterdir():
        dest = install_dir / child.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest, ignore_errors=True)
            else:
                try:
                    dest.unlink()
                except OSError:
                    pass
        if child.is_dir():
            shutil.copytree(child, dest)
        else:
            shutil.copy2(child, dest)


def check_python() -> tuple[bool, str]:
    try:
        ver = sys.version_info
        if ver[:2] < (3, 10):
            return False, f"Python {ver.major}.{ver.minor} too old (need 3.10+)"
        return True, f"{ver.major}.{ver.minor}.{ver.micro}"
    except Exception as exc:
        return False, str(exc)


def _win_no_window_flags() -> int:
    """DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW"""
    return (
        getattr(os, "DETACHED_PROCESS", 0x00000008)
        | getattr(os, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        | 0x08000000  # CREATE_NO_WINDOW
    )


def _pythonw() -> str:
    """Prefer pythonw.exe so post-update restart never leaves a console."""
    exe = sys.executable
    if sys.platform == "win32" and exe.lower().endswith("python.exe"):
        candidate = exe[:-10] + "pythonw.exe"
        if Path(candidate).is_file():
            return candidate
    return exe


def restart_app(job: dict) -> None:
    """
    Relaunch the GUI without a visible cmd.exe / start.bat window.

    start.bat is for first-run setup (echoes, ensure_deps). After a verified
    update, deps were already refreshed — open main.py via pythonw silently.
    """
    restart = job.get("restart") or {}
    bat = Path(str(restart.get("bat") or ""))
    cwd = Path(str(restart.get("cwd") or (bat.parent if bat else ".")))
    main_py = cwd / "src" / "main.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(cwd / "src")

    if main_py.is_file():
        kwargs: dict = {
            "cwd": str(cwd),
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = _win_no_window_flags()
        subprocess.Popen([_pythonw(), str(main_py)], **kwargs)
        return

    # Last resort: start.bat, still hidden on Windows
    if bat.is_file():
        if sys.platform == "win32":
            subprocess.Popen(
                ["cmd.exe", "/c", str(bat)],
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=_win_no_window_flags(),
            )
        else:
            subprocess.Popen([str(bat)], cwd=str(cwd))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, help="Path to update_job.json")
    args = ap.parse_args()
    job_path = Path(args.job)
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _log(f"FATAL: cannot read job: {exc}")
        return 2

    install_dir = Path(job["install_dir"])
    payload_dir = Path(job["payload_dir"])
    backup_dir = Path(job["backup_dir"])
    pid = int(job.get("pid") or 0)

    _log(
        f"apply start install={install_dir} payload={payload_dir} "
        f"{job.get('current_version')} -> {job.get('remote_version')}"
    )

    wait_for_pid(pid)
    time.sleep(0.8)

    if not payload_dir.is_dir():
        _log("FATAL: payload missing")
        return 3

    ok_py, py_msg = check_python()
    _log(f"python check: ok={ok_py} {py_msg}")
    if not ok_py:
        _log("FATAL: python incompatible — abort without touching install")
        return 4

    try:
        backup_install(install_dir, backup_dir)
        _log(f"backup ok -> {backup_dir}")
        _copy_tree(payload_dir, install_dir)
        _log("copy ok")
    except Exception as exc:
        _log(f"ERROR during update: {exc}; restoring backup")
        try:
            restore_backup(backup_dir, install_dir)
            _log("restore ok")
        except Exception as exc2:
            _log(f"FATAL restore failed: {exc2}")
            return 5
        return 6

    # Optional: refresh deps quietly (best-effort; failure does not roll back)
    ensure = install_dir / "scripts" / "ensure_deps.py"
    py_console = sys.executable.replace("pythonw.exe", "python.exe")
    if ensure.is_file():
        try:
            run_kw: dict = {
                "cwd": str(install_dir),
                "timeout": 300,
                "check": False,
                "env": {**os.environ, "PYTHONPATH": str(install_dir / "src")},
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                run_kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            subprocess.run([py_console, str(ensure), "--quiet"], **run_kw)
            _log("ensure_deps finished")
        except Exception as exc:
            _log(f"ensure_deps skipped: {exc}")

    marker = Path(
        os.environ.get("LOCALAPPDATA") or "."
    ) / "EasyBlockFinder4000" / "updates" / "last_apply_ok.json"
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "remote_version": job.get("remote_version"),
                    "time": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass

    restart_app(job)
    _log("restart launched; done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
