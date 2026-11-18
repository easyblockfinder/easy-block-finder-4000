from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.best_hash_store import (  # noqa: E402
    load_best_hash_state,
    save_best_hash_state,
    upsert_record_if_better,
)


def test_upsert_better_and_reject_worse(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    first = "00000000" + "ff" * 28
    r1 = upsert_record_if_better(
        "btc",
        hash_be_hex=first,
        nonce_hex="00000001",
        job_id="j1",
        nbits="1d00ffff",
        network_difficulty_at_time=1.0,
    )
    assert r1 is not None
    assert load_best_hash_state()["records"]["btc"].nonce_hex == "00000001"

    r_bad = upsert_record_if_better(
        "btc",
        hash_be_hex="00000001" + "00" * 28,
        nonce_hex="00000002",
        job_id="j2",
        nbits="1d00ffff",
        network_difficulty_at_time=1.0,
    )
    assert r_bad is None

    r2 = upsert_record_if_better(
        "btc",
        hash_be_hex="00000000" + "fe" * 28,
        nonce_hex="00000003",
        job_id="j3",
        nbits="1d00ffff",
        network_difficulty_at_time=1.0,
    )
    assert r2 is not None
    assert r2.nonce_hex == "00000003"


def test_btc_and_bch_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    upsert_record_if_better(
        "btc",
        hash_be_hex="00000000" + "11" * 28,
        nonce_hex="1",
        job_id="a",
        nbits="1d00ffff",
        network_difficulty_at_time=1.0,
    )
    upsert_record_if_better(
        "bch",
        hash_be_hex="00000000" + "22" * 28,
        nonce_hex="2",
        job_id="b",
        nbits="1d00ffff",
        network_difficulty_at_time=1.0,
    )
    st = load_best_hash_state()
    assert st["records"]["btc"].nonce_hex == "1"
    assert st["records"]["bch"].nonce_hex == "2"


def test_unknown_network_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert (
        upsert_record_if_better(
            "ltc",
            hash_be_hex="00000000" + "aa" * 28,
            nonce_hex="1",
            job_id="x",
            nbits="1d00ffff",
            network_difficulty_at_time=1.0,
        )
        is None
    )


def test_load_ignores_unknown_network_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from app_meta import APP_DATA_DIRNAME

    folder = tmp_path / APP_DATA_DIRNAME
    folder.mkdir(parents=True)
    folder.joinpath("best_hash_records.json").write_text(
        json.dumps(
            {
                "mode": "gpu_batch",
                "records": {
                    "btc": {
                        "hash_be_hex": "00000000" + "11" * 28,
                        "difficulty": 1.0,
                        "nonce_hex": "n",
                        "job_id": "j",
                        "nbits": "1d00ffff",
                        "network_difficulty_at_time": 1.0,
                        "found_at_iso": "2026-01-01T00:00:00+00:00",
                    },
                    "doge": {
                        "hash_be_hex": "00" * 64,
                        "difficulty": 1.0,
                        "nonce_hex": "x",
                        "job_id": "y",
                        "nbits": "1d00ffff",
                        "network_difficulty_at_time": 1.0,
                        "found_at_iso": "2026-01-01T00:00:00+00:00",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    st = load_best_hash_state()
    assert list(st["records"].keys()) == ["btc"]


def test_default_mode_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    st = load_best_hash_state()
    assert st["mode"] == "gpu_batch"
    assert st["records"] == {}


def test_load_skips_invalid_hash_be_hex(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from app_meta import APP_DATA_DIRNAME

    folder = tmp_path / APP_DATA_DIRNAME
    folder.mkdir(parents=True)
    folder.joinpath("best_hash_records.json").write_text(
        json.dumps(
            {
                "mode": "gpu_batch",
                "records": {
                    "btc": {
                        "hash_be_hex": "not-valid-hex",
                        "difficulty": 1.0,
                        "nonce_hex": "n",
                        "job_id": "j",
                        "nbits": "1d00ffff",
                        "network_difficulty_at_time": 1.0,
                        "found_at_iso": "2026-01-01T00:00:00+00:00",
                    },
                    "bch": {
                        "hash_be_hex": "00000000" + "22" * 28,
                        "difficulty": 1.0,
                        "nonce_hex": "x",
                        "job_id": "y",
                        "nbits": "1d00ffff",
                        "network_difficulty_at_time": 1.0,
                        "found_at_iso": "2026-01-01T00:00:00+00:00",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    st = load_best_hash_state()
    assert list(st["records"].keys()) == ["bch"]


def test_upsert_replaces_corrupt_existing_record(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from app_meta import APP_DATA_DIRNAME

    folder = tmp_path / APP_DATA_DIRNAME
    folder.mkdir(parents=True)
    folder.joinpath("best_hash_records.json").write_text(
        json.dumps(
            {
                "mode": "gpu_batch",
                "records": {
                    "btc": {
                        "hash_be_hex": "short",
                        "difficulty": 1.0,
                        "nonce_hex": "old",
                        "job_id": "j",
                        "nbits": "1d00ffff",
                        "network_difficulty_at_time": 1.0,
                        "found_at_iso": "2026-01-01T00:00:00+00:00",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    good = "00000000" + "aa" * 28
    r = upsert_record_if_better(
        "btc",
        hash_be_hex=good,
        nonce_hex="new",
        job_id="j2",
        nbits="1d00ffff",
        network_difficulty_at_time=1.0,
    )
    assert r is not None
    assert load_best_hash_state()["records"]["btc"].nonce_hex == "new"
