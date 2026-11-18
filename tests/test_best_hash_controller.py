"""Controller best-hash safety: cache, CPU verify before persist, corrupt-store, idle NET."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from app_meta import APP_DATA_DIRNAME  # noqa: E402
from mining.best_hash import (  # noqa: E402
    format_diff_short,
    idle_difficulty_row,
    verify_best_candidate,
)
from mining.best_hash_store import (  # noqa: E402
    BestHashLoadError,
    BestHashRecord,
    load_best_hash_state,
    upsert_record_if_better,
)
from mining.bitcoin import hash256  # noqa: E402
from mining.job import job_from_notify  # noqa: E402
from worker.controller import MiningController  # noqa: E402


def _snap():
    job = job_from_notify(
        ["jobA", "00" * 32, "00", "00", [], "20000000", "1d00ffff", "5a000000", True],
        "abcd",
        4,
        1.0,
        1,
    )
    return job.snapshot()


def _good_hash(snap, nonce: int) -> str:
    return hash256(snap.header_for_nonce(nonce))[::-1].hex()


def _result(hx, nonce):
    return SimpleNamespace(best_hash_be_hex=hx, best_nonce=nonce)


@pytest.fixture
def ctl(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("EBF_BEST_HASH_MODE", "gpu_batch")
    c = MiningController()
    c.network_id = "btc"
    c._load_best_into_stats("btc")
    return c


def test_verify_best_candidate_matches_and_rejects():
    snap = _snap()
    hdr = snap.header_for_nonce(7)
    good = _good_hash(snap, 7)
    assert verify_best_candidate(hdr, good) is True
    assert verify_best_candidate(hdr, "00" * 4 + "11" * 28) is False
    assert verify_best_candidate(hdr[:79], good) is False
    assert verify_best_candidate(hdr, "zz") is False


def test_cpu_verify_mismatch_not_persisted(ctl):
    snap = _snap()
    bogus = "00" * 6 + "11" * 26
    ctl._track_best_hash(snap, _result(bogus, 7), [])
    assert load_best_hash_state()["records"] == {}
    assert ctl._best_record is None
    assert ctl.stats.best_difficulty is None


def test_verified_candidate_persisted_without_celebration_first_time(ctl):
    snap = _snap()
    ctl._track_best_hash(snap, _result(_good_hash(snap, 7), 7), [])
    rec = load_best_hash_state()["records"]["btc"].gpu_best
    assert rec.nonce_hex == "00000007"
    assert ctl._best_record is not None
    assert ctl._best_broken_pending is False


def test_worse_than_cache_skips_verify_and_disk(ctl, monkeypatch):
    snap = _snap()
    ctl._best_record = upsert_record_if_better(
        "btc",
        hash_be_hex="00" * 31 + "01",
        nonce_hex="0",
        job_id="x",
        nbits="1d00ffff",
        network_difficulty_at_time=1.0,
        kind="gpu",
    )
    import worker.controller as wc

    def boom(*a, **k):
        raise AssertionError("must not verify/upsert when not better than cache")

    monkeypatch.setattr(wc, "verify_best_candidate", boom)
    monkeypatch.setattr(wc, "upsert_record_if_better", boom)
    ctl._track_best_hash(snap, _result(_good_hash(snap, 7), 7), [])


def test_improvement_after_existing_record_celebrates(ctl):
    snap = _snap()
    ctl._best_record = upsert_record_if_better(
        "btc",
        hash_be_hex="ff" * 32,
        nonce_hex="0",
        job_id="x",
        nbits="1d00ffff",
        network_difficulty_at_time=1.0,
        kind="gpu",
    )
    ctl._track_best_hash(snap, _result(_good_hash(snap, 9), 9), [])
    assert ctl._best_broken_pending is True
    assert load_best_hash_state()["records"]["btc"].gpu_best.nonce_hex == "00000009"


def test_accepted_best_updates_separately(ctl):
    snap = _snap()
    hx = _good_hash(snap, 11)
    hdr = snap.header_for_nonce(11)
    ctl._track_accepted_best(
        {
            "hash": hx,
            "nonce_hex": "0000000b",
            "job_id": "jobA",
            "nbits": "1d00ffff",
            "header80": hdr.hex(),
        }
    )
    net = load_best_hash_state()["records"]["btc"]
    assert net.accepted_best is not None
    assert net.accepted_best.nonce_hex == "0000000b"
    assert net.gpu_best is None
    assert ctl._accepted_broken_pending is False  # first accepted: no celebration


def test_accepted_best_improvement_celebrates(ctl):
    snap = _snap()
    # Weak baseline on disk + in cache
    weak = upsert_record_if_better(
        "btc",
        hash_be_hex="ff" * 32,
        nonce_hex="0",
        job_id="x",
        nbits="1d00ffff",
        network_difficulty_at_time=1.0,
        kind="accepted",
    )
    assert weak is not None
    ctl._accepted_best_record = weak
    hx = _good_hash(snap, 11)
    hdr = snap.header_for_nonce(11)
    ctl._track_accepted_best(
        {
            "hash": hx,
            "nonce_hex": "0000000b",
            "job_id": "jobA",
            "nbits": "1d00ffff",
            "header80": hdr.hex(),
        }
    )
    assert ctl._accepted_broken_pending is True
    assert load_best_hash_state()["records"]["btc"].accepted_best.hash_be_hex == hx


def test_accepted_only_mode_skips_gpu_track(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("EBF_BEST_HASH_MODE", "accepted_only")
    c = MiningController()
    c.network_id = "btc"
    c._load_best_into_stats("btc")
    snap = _snap()
    c._track_best_hash(snap, _result(_good_hash(snap, 5), 5), [])
    assert load_best_hash_state()["records"] == {}


def _store_file(tmp_path: Path) -> Path:
    folder = tmp_path / APP_DATA_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "best_hash_records.json"


def test_corrupt_store_not_overwritten_by_upsert(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    f = _store_file(tmp_path)
    f.write_text("{not json", encoding="utf-8")
    with pytest.raises(BestHashLoadError):
        upsert_record_if_better(
            "btc",
            hash_be_hex="00" * 4 + "11" * 28,
            nonce_hex="1",
            job_id="j",
            nbits="1d00ffff",
            network_difficulty_at_time=1.0,
        )
    assert f.read_text(encoding="utf-8") == "{not json"


def test_controller_load_quarantines_corrupt_store(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    f = _store_file(tmp_path)
    f.write_text("{not json", encoding="utf-8")
    c = MiningController()
    c._load_best_into_stats("btc")
    assert not f.exists()
    assert f.with_suffix(".json.bak").read_text(encoding="utf-8") == "{not json"
    assert c._best_store_ok is True


def test_transient_load_error_disables_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import worker.controller as wc

    def fail(*a, **k):
        raise BestHashLoadError("locked", corrupt=False)

    monkeypatch.setattr(wc, "load_best_hash_state", fail)
    monkeypatch.setenv("EBF_BEST_HASH_MODE", "gpu_batch")
    c = MiningController()
    c.network_id = "btc"
    c._load_best_into_stats("btc")
    assert c._best_store_ok is False
    snap = _snap()
    c._track_best_hash(snap, _result(_good_hash(snap, 7), 7), [])
    assert not _store_file(tmp_path).exists()


def test_idle_row_net_is_none_best_kept():
    net, best = idle_difficulty_row(12.5)
    assert net is None and best == 12.5
    assert format_diff_short(net) == "\u2014"
    assert idle_difficulty_row(None) == (None, None)
