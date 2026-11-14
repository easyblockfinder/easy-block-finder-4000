"""Writes the most suitable python.exe path for SoloBlockStrike on this PC to stdout."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _candidates() -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(path: str | None) -> None:
        if not path:
            return
        p = str(Path(path).resolve())
        key = p.lower()
        if key in seen:
            return
        if not Path(p).is_file():
            return
        seen.add(key)
        found.append(p)

    # 1) Python / Python3 in PATH (where packages are usually installed)
    for name in ("python", "python3"):
        add(shutil.which(name))

    # 2) py launcher — all versions
    py = shutil.which("py")
    if py:
        for args in (["-3.12"], ["-3.11"], ["-3.10"], ["-3.13"], ["-3"], []):
            try:
                out = subprocess.check_output(
                    [py, *args, "-c", "import sys; print(sys.executable)"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                ).strip()
                add(out)
            except Exception:
                pass

    # 3) Bilinen kurulum dizinleri
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    for pattern in (
        r"C:\Python3*\python.exe",
        str(local / r"Programs\Python\Python3*\python.exe"),
    ):
        parent = Path(pattern).parent
        try:
            root = parent.parent if parent.name.startswith("Python") else Path(r"C:\\")
        except Exception:
            root = Path("C:/")
        # glob
    for base in (Path(r"C:\\"), local / "Programs" / "Python"):
        if not base.exists():
            continue
        try:
            for p in base.glob("Python3*/python.exe"):
                add(str(p))
            for p in base.glob("Python3*/python3*.exe"):
                # free-threaded *t.exe to be excluded below
                add(str(p))
        except Exception:
            pass

    return found


def _score(exe: str) -> tuple:
    """High score = preference. Discard non-working / free-threaded."""
    name = Path(exe).name.lower()
    # free-threaded (3.13t) PyQt6 has no wheel — requires source compilation
    if name.endswith("t.exe") or "python3.13t" in name:
        return (-100, 0, 0, exe)

    try:
        code = (
            "import sys\n"
            "print(sys.version_info.major)\n"
            "print(sys.version_info.minor)\n"
            "mods=0\n"
            "for m in ('PyQt6','numpy','pyopencl','base58','bech32','pynvml'):\n"
            "  try:\n"
            "    __import__(m); mods+=1\n"
            "  except Exception:\n"
            "    pass\n"
            "print(mods)\n"
        )
        out = subprocess.check_output(
            [exe, "-c", code],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=20,
        ).strip().splitlines()
        major, minor, mods = int(out[0]), int(out[1]), int(out[2])
    except Exception:
        return (-50, 0, 0, exe)

    if major != 3 or minor < 10:
        return (-40, minor, mods, exe)

    # Priority: number of installed packages, then around 3.12
    ver_pref = 20 if minor == 12 else (10 if minor in (11, 13) else 5)
    return (mods * 10 + ver_pref, minor, mods, exe)


def main() -> int:
    cands = _candidates()
    if not cands:
        print("NO_PYTHON", file=sys.stderr)
        return 1
    ranked = sorted((_score(c) for c in cands), reverse=True)
    best = ranked[0]
    score, _minor, mods, exe = best[0], best[1], best[2], best[3]
    if score < 0:
        print("NO_PYTHON", file=sys.stderr)
        return 1
    # Brief information to stderr (not captured by bat)
    print(f"secilen: {exe} (paket={mods}/6)", file=sys.stderr)
    print(exe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
