from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.dag_gate import (  # noqa: E402
    _AUTOLYKOS_N_BASE,
    autolykos2_dataset_bytes,
    calc_autolykos2_n,
)


def test_n_before_increase():
    assert calc_autolykos2_n(0) == _AUTOLYKOS_N_BASE
    assert calc_autolykos2_n(614_399) == _AUTOLYKOS_N_BASE


def test_n_grows_at_boundaries():
    n0 = calc_autolykos2_n(614_400)
    assert n0 == (_AUTOLYKOS_N_BASE // 100) * 105
    n1 = calc_autolykos2_n(614_400 + 51_200)
    assert n1 == (n0 // 100) * 105
    assert n1 > n0


def test_n_capped():
    assert calc_autolykos2_n(4_198_400) == 2_143_944_600
    assert calc_autolykos2_n(9_999_999) == 2_143_944_600


def test_dataset_bytes_is_n_times_31():
    ds, n = autolykos2_dataset_bytes(1000)
    assert ds == n * 31
