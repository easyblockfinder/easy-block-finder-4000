"""Eski mining donationi kapali; manuel Donate adresleri."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from donate_addresses import DONATE_OPTIONS, get_donate_option  # noqa: E402
from mining.app_donation import (  # noqa: E402
    in_donation_slice,
    is_effectively_enabled,
    normalize_app_donation,
)
from ui.donate_dialog import qr_pixmap  # noqa: E402


def test_normalize_always_disabled():
    cfg = normalize_app_donation(
        {
            "enabled": True,
            "ack_full_reward_warning": True,
            "percent": 10,
            "donation_address_by_network": {"btc": "bc1qtest"},
        }
    )
    assert cfg["enabled"] is False
    assert is_effectively_enabled(cfg, "btc") is False


def test_slice_never_active():
    assert in_donation_slice(594.0, 1.0, cycle_s=600.0) is False
    assert in_donation_slice(0.0, 50.0, cycle_s=600.0) is False


def test_donate_addresses_present():
    assert len(DONATE_OPTIONS) == 5
    btc = get_donate_option("btc")
    assert btc is not None
    assert btc.address.startswith("bc1q")
    bch = get_donate_option("bch")
    assert bch is not None
    assert bch.qr_payload.startswith("bitcoincash:")
    assert get_donate_option("bnb") is not None
    assert get_donate_option("sol") is not None
    assert get_donate_option("usdt_trc20") is not None


def test_qr_pixmap_builds():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    pm = qr_pixmap("bc1q4t3ax0xj8lpv6t8vhnv3x0jmth723x7l86rsak", modules=4)
    assert app is not None
    assert not pm.isNull()
    assert pm.width() > 40
