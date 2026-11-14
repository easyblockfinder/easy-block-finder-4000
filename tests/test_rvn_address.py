from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.bitcoin import validate_address_for_network, validate_rvn_address  # noqa: E402


def test_rvn_prefix():
    ok, _ = validate_rvn_address("")
    assert not ok
    ok, _ = validate_rvn_address("bc1qtest")
    assert not ok
    # Gecersiz checksum — R with baslasa eandn
    ok, _ = validate_rvn_address("R" + ("1" * 33))
    assert not ok
