"""Windows Defender / MOTW yardimcilari."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.windows_security import (  # noqa: E402
    defender_exclusion_help,
    exe_quarantined_or_missing,
    looks_like_defender_block,
    solo_blockstrike_root,
    winerror_code,
)


def test_looks_like_defender_block_winerror():
    exc = OSError(225, "virus")
    exc.winerror = 225  # type: ignore[attr-defined]
    assert looks_like_defender_block(exc) is True


def test_looks_like_defender_block_message():
    assert looks_like_defender_block(RuntimeError("Windows Defender quarantine")) is True
    assert looks_like_defender_block(RuntimeError("connection lost")) is False


def test_winerror_code():
    exc = OSError("x")
    exc.winerror = 226  # type: ignore[attr-defined]
    assert winerror_code(exc) == 226


def test_exe_quarantined_missing(tmp_path):
    assert exe_quarantined_or_missing(tmp_path / "nope.exe") is True
    p = tmp_path / "ok.exe"
    p.write_bytes(b"MZ" + b"\0" * 62)
    assert exe_quarantined_or_missing(p) is False


def test_defender_help_mentions_root():
    msg = defender_exclusion_help("XMRig")
    assert "Easy Block Finder 4000" in msg or "EBF4000" in msg
    assert (
        str(solo_blockstrike_root()) in msg
        or "LOCALAPPDATA" in msg.upper()
        or "EasyBlockFinder4000" in msg
    )
