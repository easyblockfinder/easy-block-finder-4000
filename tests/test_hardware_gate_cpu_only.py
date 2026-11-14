from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from monitor import hardware_gate as hg  # noqa: E402


def test_cpu_only_blocks_gpu_networks(monkeypatch, tmp_path):
    monkeypatch.setattr(hg, "MARKER", tmp_path / ".deps_ok")
    (tmp_path / ".deps_ok").write_text("cpu-only\n", encoding="utf-8")
    monkeypatch.delenv("SOLOBLOCKSTRIKE_CPU_ONLY", raising=False)
    hg._gpu_cache = None
    assert hg.deps_mode() == "cpu-only"
    assert hg.network_block_reason("xmr") is None
    assert hg.network_block_reason("btc") is not None
    assert "CPU-only" in (hg.network_block_reason("btc") or "")
    assert hg.network_block_reason("rvn") is not None


def test_env_cpu_only(monkeypatch, tmp_path):
    monkeypatch.setattr(hg, "MARKER", tmp_path / ".deps_ok")
    monkeypatch.setenv("SOLOBLOCKSTRIKE_CPU_ONLY", "1")
    hg._gpu_cache = None
    assert hg.deps_mode() == "cpu-only"
    assert hg.network_block_reason("bch") is not None


def test_select_page_no_opencl_probe_when_full(monkeypatch, tmp_path):
    monkeypatch.setattr(hg, "MARKER", tmp_path / ".deps_ok")
    (tmp_path / ".deps_ok").write_text("full\n", encoding="utf-8")
    monkeypatch.delenv("SOLOBLOCKSTRIKE_CPU_ONLY", raising=False)
    called = {"n": 0}

    def boom():
        called["n"] += 1
        return False, "should not probe"

    monkeypatch.setattr(hg, "opencl_gpu_available", boom)
    monkeypatch.setattr(hg, "opencl_nvidia_available", boom)
    assert hg.network_block_reason("btc", probe_gpu=False) is None
    assert called["n"] == 0
    assert hg.network_block_reason("btc", probe_gpu=True) is not None
    assert called["n"] == 1
