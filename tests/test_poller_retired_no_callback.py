from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.rigel_runner import RigelRunner  # noqa: E402
from engines.xmrig_runner import XmrigRunner  # noqa: E402


def test_xmrig_error_path_no_callback_after_retire():
    r = XmrigRunner(Path("xmrig.exe"), host="h", port=1, username="u", generation=1)
    hits = []
    r.on_snapshot = lambda s: hits.append(s)
    r._proc = MagicMock()
    r._proc.poll.return_value = None
    r.retire()
    # Hata yolu simulasyonu (poll_loop except govdesi)
    with r._lock:
        assert r._retired
        cb = r.on_snapshot
    assert cb is None
    assert hits == []


def test_rigel_error_path_no_callback_after_retire():
    r = RigelRunner(
        Path("rigel.exe"),
        algorithm="kawpow",
        coin="rvn",
        host="h",
        port=1,
        username="u",
        generation=2,
    )
    hits = []
    r.on_snapshot = lambda s: hits.append(1)
    r.retire()
    with r._lock:
        cb = r.on_snapshot
        retired = r._retired
    assert retired and cb is None
    assert hits == []
