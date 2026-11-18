"""Updater must preserve or install bundled runtime without wiping AppData."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import apply_update as au  # noqa: E402


def test_skip_names_includes_runtime():
    assert "runtime" in au.SKIP_NAMES


def test_ensure_runtime_keeps_existing(tmp_path):
    payload = tmp_path / "payload"
    install = tmp_path / "install"
    (payload / "runtime").mkdir(parents=True)
    (payload / "runtime" / "python.exe").write_text("new", encoding="utf-8")
    (install / "runtime").mkdir(parents=True)
    (install / "runtime" / "python.exe").write_text("old", encoding="utf-8")
    au._ensure_runtime_from_payload(payload, install)
    assert (install / "runtime" / "python.exe").read_text(encoding="utf-8") == "old"


def test_ensure_runtime_installs_when_missing(tmp_path):
    payload = tmp_path / "payload"
    install = tmp_path / "install"
    install.mkdir()
    (payload / "runtime").mkdir(parents=True)
    (payload / "runtime" / "python.exe").write_text("bundled", encoding="utf-8")
    (payload / "runtime" / "extra.txt").write_text("x", encoding="utf-8")
    au._ensure_runtime_from_payload(payload, install)
    assert (install / "runtime" / "python.exe").read_text(encoding="utf-8") == "bundled"
    assert (install / "runtime" / "extra.txt").is_file()
