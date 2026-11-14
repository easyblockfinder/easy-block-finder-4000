from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from networks.profiles import get_profile  # noqa: E402


def test_xmr_kryptex_stats_url_wallet_without_solo_prefix():
    p = get_profile("xmr")
    addr = "4" + "A" * 94  # format testi; real checksum not
    url = p.stats_url_for(addr)
    assert url == f"https://pool.kryptex.com/xmr/miner/stats/{addr}"
    assert "/solo:" not in url
    assert p.username_for(addr) == f"solo:{addr}"
    assert p.explorer_kind == "none"


def test_rvn_erg_still_account_links_not_explorer():
    assert get_profile("rvn").explorer_kind == "none"
    assert "2miners.com/account/" in get_profile("rvn").stats_url_for("Raddr")
    assert get_profile("erg").explorer_kind == "none"
