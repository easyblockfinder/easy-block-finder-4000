from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.dag_gate import (  # noqa: E402
    autolykos2_dataset_bytes,
    check_autolykos_vram,
    check_kawpow_vram,
    kawpow_dag_bytes,
)


def test_kawpow_dag_grows_with_epoch():
    d0, e0 = kawpow_dag_bytes(0)
    d1, e1 = kawpow_dag_bytes(7500)
    assert e0 == 0 and e1 == 1
    assert d1 > d0


def test_vram_gate_rejects_low_free():
    dag, _ = kawpow_dag_bytes(100_000)
    overhead = 512 * 1024 * 1024
    free = dag // 2
    r = check_kawpow_vram(
        free_vram_bytes=free,
        total_vram_bytes=4 * 1024 * 1024 * 1024,
        height=100_000,
        overhead_bytes=overhead,
    )
    assert r.ok is False
    # Message language may change; gate must cite insufficient free VRAM.
    assert "Insufficient free VRAM" in r.message
    assert "free=" in r.message


def test_vram_gate_accepts_enough_free():
    dag, _ = kawpow_dag_bytes(1000)
    overhead = 512 * 1024 * 1024
    free = dag + overhead + 100
    r = check_kawpow_vram(
        free_vram_bytes=free,
        total_vram_bytes=8 * 1024 * 1024 * 1024,
        height=1000,
        overhead_bytes=overhead,
    )
    assert r.ok is True


def test_autolykos_gate_rejects_low_free():
    ds, _ = autolykos2_dataset_bytes(500_000)
    overhead = 512 * 1024 * 1024
    r = check_autolykos_vram(
        free_vram_bytes=ds // 3,
        total_vram_bytes=4 * 1024 * 1024 * 1024,
        height=500_000,
        overhead_bytes=overhead,
    )
    assert r.ok is False
