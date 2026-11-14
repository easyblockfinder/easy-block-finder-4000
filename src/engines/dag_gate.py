"""KawPoW / Autolykos memory gate — free VRAM vs. DAG/dataset + overhead."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Optional

from app_meta import APP_USER_AGENT


@dataclass(frozen=True)
class MemoryGateResult:
    ok: bool
    height: Optional[int]
    epoch: Optional[int]
    dag_or_dataset_bytes: int
    overhead_bytes: int
    free_vram_bytes: int
    total_vram_bytes: int
    message: str

    @property
    def required_bytes(self) -> int:
        return self.dag_or_dataset_bytes + self.overhead_bytes


def fetch_rvn_height(timeout_s: float = 15.0) -> int:
    """2Miners solo API veya yedek."""
    urls = (
        "https://solo-rvn.2miners.com/api/stats",
        "https://rvn.2miners.com/api/stats",
    )
    last_err: Exception | None = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": APP_USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            nodes = data.get("nodes") or []
            if nodes and isinstance(nodes, list):
                h = nodes[0].get("height")
                if h is not None:
                    return int(h)
            # some answers
            for key in ("height", "network_height", "nHeight"):
                if key in data and data[key] is not None:
                    return int(data[key])
        except Exception as exc:
            last_err = exc
            continue
    raise RuntimeError(f"Could not fetch RVN height: {last_err}")


def kawpow_dag_bytes(height: int) -> tuple[int, int]:
    """
    Ravencoin KawPoW: epoch = height // 7500.
    DAG ~= 1 GiB + 8 MiB * epoch (common rule of thumb; confirm with miner/epoch).
    """
    if height < 0:
        raise ValueError("height negatif")
    epoch = height // 7500
    dag = (1024 * 1024 * 1024) + epoch * (8 * 1024 * 1024)
    return dag, epoch


def check_kawpow_vram(
    *,
    free_vram_bytes: int,
    total_vram_bytes: int,
    height: Optional[int] = None,
    overhead_bytes: int = 512 * 1024 * 1024,
) -> MemoryGateResult:
    if height is None:
        height = fetch_rvn_height()
    dag, epoch = kawpow_dag_bytes(height)
    required = dag + overhead_bytes
    ok = free_vram_bytes >= required
    msg = (
        f"free={free_vram_bytes // (1024*1024)}MB "
        f"required={required // (1024*1024)}MB "
        f"(DAG≈{dag // (1024*1024)}MB + overhead={overhead_bytes // (1024*1024)}MB) "
        f"total={total_vram_bytes // (1024*1024)}MB "
        f"height={height} epoch={epoch}"
    )
    if not ok:
        msg = "Insufficient free VRAM — " + msg
    return MemoryGateResult(
        ok=ok,
        height=height,
        epoch=epoch,
        dag_or_dataset_bytes=dag,
        overhead_bytes=overhead_bytes,
        free_vram_bytes=free_vram_bytes,
        total_vram_bytes=total_vram_bytes,
        message=msg,
    )


def fetch_erg_height(timeout_s: float = 15.0) -> int:
    urls = (
        "https://solo-erg.2miners.com/api/stats",
        "https://erg.2miners.com/api/stats",
    )
    last_err: Exception | None = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": APP_USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            nodes = data.get("nodes") or []
            if nodes and isinstance(nodes, list):
                h = nodes[0].get("height")
                if h is not None:
                    return int(h)
        except Exception as exc:
            last_err = exc
            continue
    raise RuntimeError(f"Could not fetch ERG height: {last_err}")


# Autolykos2 N — ergo AutolykosPowScheme.scala / papers/yellow/pow/ErgoPow.tex
# NBase=2^26; IncreaseStart=600*1024; IncreasePeriod=50*1024; MaxHeight=4198400
# At each step, N = N/100*105 (integer); element size 31 bytes.
_AUTOLYKOS_N_BASE = 1 << 26  # 67_108_864
_AUTOLYKOS_INCREASE_START = 600 * 1024  # 614_400
_AUTOLYKOS_INCREASE_PERIOD = 50 * 1024  # 51_200
_AUTOLYKOS_N_MAX_HEIGHT = 4_198_400
_AUTOLYKOS_N_CAP = 2_143_944_600
_AUTOLYKOS_ELEM_BYTES = 31


def calc_autolykos2_n(height: int) -> int:
    """Number of elements in the table N (Autolykos2)."""
    if height < 0:
        raise ValueError("height negatif")
    h = min(int(height), _AUTOLYKOS_N_MAX_HEIGHT)
    if h < _AUTOLYKOS_INCREASE_START:
        return _AUTOLYKOS_N_BASE
    iters = (h - _AUTOLYKOS_INCREASE_START) // _AUTOLYKOS_INCREASE_PERIOD + 1
    n = _AUTOLYKOS_N_BASE
    for _ in range(iters):
        n = (n // 100) * 105
    if h >= _AUTOLYKOS_N_MAX_HEIGHT:
        return _AUTOLYKOS_N_CAP
    return n


def autolykos2_dataset_bytes(height: int) -> tuple[int, int]:
    """
    Dataset bayt ≈ N * 31.
    Kaynak: ergo AutolykosPowScheme.calcN + ErgoPow.tex Table N.
    Returns: (dataset_bytes, N).
    """
    n = calc_autolykos2_n(height)
    return n * _AUTOLYKOS_ELEM_BYTES, n


def check_autolykos_vram(
    *,
    free_vram_bytes: int,
    total_vram_bytes: int,
    height: Optional[int] = None,
    overhead_bytes: int = 512 * 1024 * 1024,
    height_known: bool = True,
) -> MemoryGateResult:
    """
    height_known=False: chain height unknown — do not treat estimate as exact;
    gate fails (fail-safe).
    """
    if height is None:
        if not height_known:
            return MemoryGateResult(
                ok=False,
                height=None,
                epoch=None,
                dag_or_dataset_bytes=0,
                overhead_bytes=overhead_bytes,
                free_vram_bytes=free_vram_bytes,
                total_vram_bytes=total_vram_bytes,
                message=(
                    "Could not fetch Ergo height — Autolykos2 VRAM gate "
                    "estimate not treated as exact; not started."
                ),
            )
        height = fetch_erg_height()
    ds, n_val = autolykos2_dataset_bytes(height)
    required = ds + overhead_bytes
    ok = free_vram_bytes >= required
    msg = (
        f"free={free_vram_bytes // (1024*1024)}MB "
        f"required={required // (1024*1024)}MB "
        f"(dataset={ds // (1024*1024)}MB = N*{_AUTOLYKOS_ELEM_BYTES}B + "
        f"overhead={overhead_bytes // (1024*1024)}MB) "
        f"total={total_vram_bytes // (1024*1024)}MB "
        f"height={height} N={n_val}"
    )
    if not ok:
        msg = "Insufficient free VRAM — " + msg
    return MemoryGateResult(
        ok=ok,
        height=height,
        epoch=n_val,
        dag_or_dataset_bytes=ds,
        overhead_bytes=overhead_bytes,
        free_vram_bytes=free_vram_bytes,
        total_vram_bytes=total_vram_bytes,
        message=msg,
    )
