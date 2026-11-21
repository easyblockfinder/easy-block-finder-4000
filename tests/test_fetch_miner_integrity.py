from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines import fetch_miner as fm  # noqa: E402


def _make_zip(exe_name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"pkg/{exe_name}", content)
    return buf.getvalue()


def test_modified_exe_rejected(tmp_path, monkeypatch):
    """Tampered on-disk EXE is re-extracted from the verified ZIP (official host only)."""
    payload = b"MZ-good-miner-binary"
    zbytes = _make_zip("dummy.exe", payload)
    expect = hashlib.sha256(zbytes).hexdigest()
    lock = {
        "dummy": {
            "version": "0.0.1",
            # Keep host pin: tests must not use non-official URLs to reach extract logic.
            "url": "https://github.com/example/dummy/releases/download/v0.0.1/dummy.zip",
            "sha256": expect,
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
            self._data = zbytes
            self._pos = 0
            self.headers = {"Content-Length": str(len(zbytes))}

        def read(self, n: int = -1) -> bytes:
            if self._pos >= len(self._data):
                return b""
            if n < 0:
                chunk = self._data[self._pos :]
                self._pos = len(self._data)
                return chunk
            chunk = self._data[self._pos : self._pos + n]
            self._pos += len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(fm.urllib.request, "urlopen", lambda *_a, **_k: _Resp())

    exe = fm.ensure_miner("dummy", reverify=True, require_consent=False)
    assert exe.is_file()
    assert exe.read_bytes() == payload
    # EXE’yi boz — sessizce calistirilmaz; dogrulanmis ZIP’ten tekrar kurulur
    exe.write_bytes(b"MZ-TAMPERED")
    exe2 = fm.ensure_miner("dummy", reverify=True, require_consent=False)
    assert exe2.read_bytes() == payload


def test_zip_slip_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.exe", b"x")
    zpath = tmp_path / "x.zip"
    zpath.write_bytes(buf.getvalue())
    with zipfile.ZipFile(zpath, "r") as zf:
        with pytest.raises(RuntimeError, match="slip|birden fazla|exe yok"):
            # member secimi evil for basarheatz or slip
            try:
                m = fm._find_zip_member(zf, "evil.exe")
                fm._safe_extract_member(zf, m, tmp_path / "out")
            except RuntimeError:
                raise
