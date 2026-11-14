from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_cpu_only_skips_nvidia_steps(monkeypatch, tmp_path):
    import ensure_deps as ed

    monkeypatch.setattr(ed, "ROOT", tmp_path)
    monkeypatch.setattr(ed, "REQ", ROOT / "requirements.txt")
    monkeypatch.setattr(ed, "MARKER", tmp_path / ".deps_ok")
    monkeypatch.setattr(ed, "SRC", ROOT / "src")

    called = {"nvidia": 0, "opencl": 0, "pip": 0, "keccak": 0}

    monkeypatch.setattr(ed, "check_python", lambda: True)
    monkeypatch.setattr(ed, "remove_obsolete_cuda_packages", lambda: None)

    def boom_nvidia():
        called["nvidia"] += 1
        return False

    def boom_opencl():
        called["opencl"] += 1
        return False

    monkeypatch.setattr(ed, "check_nvidia_opencl_driver", boom_nvidia)
    monkeypatch.setattr(ed, "check_opencl_runtime", boom_opencl)
    monkeypatch.setattr(ed, "check_nvml", lambda: True)

    def fake_pip():
        called["pip"] += 1
        return True

    def fake_keccak():
        called["keccak"] += 1
        return True

    monkeypatch.setattr(ed, "ensure_pip_packages", fake_pip)
    # ensure_pip calls ensure_keccak internally — stub whole pip path
    monkeypatch.setattr(
        ed,
        "ensure_pip_packages",
        lambda: (called.__setitem__("pip", called["pip"] + 1) or True),
    )

    monkeypatch.setattr(sys, "argv", ["ensure_deps.py", "--cpu-only"])
    rc = ed.main()
    assert rc == 0
    assert called["nvidia"] == 0
    assert called["opencl"] == 0
    assert called["pip"] == 1
    assert (tmp_path / ".deps_ok").read_text(encoding="utf-8").strip() == "cpu-only"
