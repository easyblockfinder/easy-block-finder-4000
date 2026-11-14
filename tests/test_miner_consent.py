"""Miner download consent + catalog helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.fetch_miner import _assert_official_download_url, ensure_miner  # noqa: E402
from engines.miner_catalog import (  # noqa: E402
    consent_body_for_miners,
    get_miner_info,
    miner_id_for_network,
)
from ui.settings_store import DEFAULTS  # noqa: E402


def test_default_consent_off():
    assert DEFAULTS.get("miner_download_consent") is False


def test_miner_id_for_network():
    assert miner_id_for_network("xmr") == "xmrig"
    assert miner_id_for_network("rvn") == "rigel"
    assert miner_id_for_network("erg") == "rigel"
    assert miner_id_for_network("btc") is None
    assert miner_id_for_network("bch") is None


def test_get_miner_info_fields():
    x = get_miner_info("xmrig")
    assert x.license.startswith("GPL")
    assert "github.com" in x.url
    assert x.sha256
    r = get_miner_info("rigel")
    assert "proprietary" in r.license.lower() or "free" in r.license.lower()
    assert r.donate_percent >= 0


def test_consent_body_lists_license_and_fee():
    text = consent_body_for_miners(["xmrig"])
    assert "XMRig" in text
    assert "GPL" in text
    assert "SHA-256" in text
    assert "Defender" in text


def test_assert_official_url():
    _assert_official_download_url(
        "https://github.com/xmrig/xmrig/releases/download/v6.26.0/x.zip"
    )
    with pytest.raises(RuntimeError, match="non-official"):
        _assert_official_download_url("https://evil.example/miner.zip")


def test_ensure_miner_blocks_without_consent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engines.miner_catalog.load_consent_from_settings", lambda: False
    )
    # Force download path: empty install + missing zip
    monkeypatch.setattr(
        "engines.fetch_miner.miner_install_dir",
        lambda mid, ver: tmp_path / mid / ver,
    )
    with pytest.raises(RuntimeError, match="consent"):
        ensure_miner("xmrig", reverify=True, require_consent=True)
