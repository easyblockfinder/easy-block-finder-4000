"""Offline Engine Audit — no pool, no persistent mining stats writes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from audit.offline_runner import run_offline_engine_audit  # noqa: E402
from audit.stats import expected_cumulative, evaluate_disjoint_bands  # noqa: E402


def test_expected_cumulative_formula():
    # N / (2^32 * D)
    n = 2**32
    assert expected_cumulative(n, 1.0) == pytest.approx(1.0)
    assert expected_cumulative(n, 4200.0) == pytest.approx(1.0 / 4200.0)


def test_disjoint_bands_insufficient_at_tiny_n():
    n = 100
    counts = [100] + [0] * 11  # all meet 0.001 only roughly — synthetic
    # Just ensure API returns insufficient for high D
    fake = [n] * 7 + [0, 0, 0, 0, 0]
    bands = evaluate_disjoint_bands(n, fake)
    focus_like = [b for b in bands if b.d_lo >= 4200]
    assert focus_like
    assert all(b.status == "insufficient_sample" for b in focus_like)


def test_offline_audit_runs_without_pool(tmp_path, monkeypatch):
    # Point AppData-ish paths away; offline must not create best_hash records
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    report = run_offline_engine_audit(
        total_hashes=4096, batch_size=1024, measure_overhead=True
    )
    if report.status == "skipped":
        pytest.skip(report.message)
    assert report.status == "ok"
    assert report.attempts == 4096
    assert len(report.histogram_counts) == 12
    assert report.duplicate_ranges == 0
    assert report.extranonce_wraps == 0
    assert report.cpu_verify_failures == 0
    assert report.audit_kernel_s is not None and report.audit_kernel_s > 0
    # Measured overhead may be positive or slightly negative (noise); must be present when measured
    assert report.production_kernel_s is not None
    assert report.overhead_percent is not None
    # No best_hash_records.json written by offline path
    found = list(tmp_path.rglob("best_hash_records.json"))
    assert found == []
    # Focus evals include 4200/5000/10000
    labels = {e["label"] for e in report.focus_evals}
    assert ">= 4200.0" in labels or ">= 4200" in labels or any(
        "4200" in e["label"] for e in report.focus_evals
    )


def test_offline_report_json_serializable(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    report = run_offline_engine_audit(total_hashes=1024, batch_size=1024, measure_overhead=False)
    if report.status == "skipped":
        pytest.skip(report.message)
    raw = json.dumps(report.to_dict())
    assert "histogram_counts" in raw
