from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines import fetch_miner as fm  # noqa: E402


def test_ensure_miner_rejects_bad_sha(tmp_path, monkeypatch):
    lock = {
        "dummy": {
            "version": "0.0.1",
            "url": "https://example.invalid/dummy.zip",
            "sha256": "0" * 64,
            "asset": "dummy.zip",
            "exe_relpath": "dummy.exe",
        }
    }
    lock_path = tmp_path / "miners.lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(fm, "_LOCK_PATH", lock_path)
    monkeypatch.setattr(fm, "miner_install_dir", lambda *_a, **_k: tmp_path / "install")

    class _Resp:
        def __init__(self) -> None:
            self._done = False

        def read(self, _n: int = -1) -> bytes:
            if self._done:
                return b""
            self._done = True
            return b"not-a-valid-miner-zip"

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(
        fm.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Resp(),
    )

    with pytest.raises(RuntimeError, match="SHA-256"):
        fm.ensure_miner("dummy", reverify=True)
