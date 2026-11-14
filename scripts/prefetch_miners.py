"""
Optional CLI to prefetch official miners AFTER user consent.

Not called by start.bat. Prefer in-app consent + on-demand download for the
selected network only.

  set PYTHONPATH=src
  python scripts/prefetch_miners.py --consent-ok xmrig
  python scripts/prefetch_miners.py --consent-ok rigel
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    args = [a for a in sys.argv[1:] if a]
    if "--consent-ok" not in args:
        print(
            "Refusing to download: pass --consent-ok only after the user agreed "
            "in the app (or knowingly on this CLI)."
        )
        print("Example: python scripts/prefetch_miners.py --consent-ok xmrig")
        return 2

    ids = [a for a in args if a != "--consent-ok" and not a.startswith("-")]
    if not ids:
        print("Specify miner id(s): xmrig and/or rigel")
        return 2

    from engines.fetch_miner import ensure_miner
    from engines.miner_catalog import save_consent

    save_consent(True)
    failed: list[str] = []
    for mid in ids:
        try:
            print(f"  → {mid}…")
            exe = ensure_miner(mid, reverify=True, require_consent=True)
            print(f"    OK: {exe}")
        except Exception as exc:
            print(f"    FAIL: {mid}: {exc}")
            failed.append(mid)

    if failed:
        print("Failed:", ", ".join(failed))
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
