from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app_meta import APP_DATA_DIRNAME
from mining.best_hash import (
    SUPPORTED_BEST_HASH_NETWORKS,
    difficulty_from_hash_int,
    hash_be_hex_to_int,
    is_better_hash,
)

DEFAULT_MODE = "gpu_batch"


@dataclass
class BestHashRecord:
    hash_be_hex: str
    difficulty: float
    nonce_hex: str
    job_id: str
    nbits: str
    network_difficulty_at_time: float | None
    found_at_iso: str


def _local_app_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def _store_path() -> Path:
    folder = _local_app_data() / APP_DATA_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "best_hash_records.json"


def _record_from_dict(raw: dict[str, Any]) -> BestHashRecord | None:
    try:
        nd = raw.get("network_difficulty_at_time")
        return BestHashRecord(
            hash_be_hex=str(raw["hash_be_hex"]),
            difficulty=float(raw["difficulty"]),
            nonce_hex=str(raw["nonce_hex"]),
            job_id=str(raw["job_id"]),
            nbits=str(raw["nbits"]),
            network_difficulty_at_time=float(nd) if nd is not None else None,
            found_at_iso=str(raw["found_at_iso"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_best_hash_state() -> dict:
    path = _store_path()
    if not path.is_file():
        return {"mode": DEFAULT_MODE, "records": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"mode": DEFAULT_MODE, "records": {}}
    if not isinstance(data, dict):
        return {"mode": DEFAULT_MODE, "records": {}}
    mode = str(data.get("mode") or DEFAULT_MODE)
    raw_records = data.get("records")
    records: dict[str, BestHashRecord] = {}
    if isinstance(raw_records, dict):
        for network_id, item in raw_records.items():
            if network_id not in SUPPORTED_BEST_HASH_NETWORKS:
                continue
            if not isinstance(item, dict):
                continue
            rec = _record_from_dict(item)
            if rec is not None:
                records[str(network_id)] = rec
    return {"mode": mode, "records": records}


def save_best_hash_state(mode: str, records: dict[str, BestHashRecord]) -> None:
    path = _store_path()
    payload = {
        "mode": mode,
        "records": {
            nid: asdict(rec) for nid, rec in sorted(records.items()) if nid in SUPPORTED_BEST_HASH_NETWORKS
        },
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix="best_hash_", suffix=".json", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        tmp_path.replace(path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def upsert_record_if_better(
    network_id: str,
    *,
    hash_be_hex: str,
    nonce_hex: str,
    job_id: str,
    nbits: str,
    network_difficulty_at_time: float | None,
    found_at_iso: str | None = None,
) -> BestHashRecord | None:
    if network_id not in SUPPORTED_BEST_HASH_NETWORKS:
        return None
    try:
        candidate_int = hash_be_hex_to_int(hash_be_hex)
    except ValueError:
        return None
    state = load_best_hash_state()
    mode = state["mode"]
    records: dict[str, BestHashRecord] = dict(state["records"])
    existing = records.get(network_id)
    existing_int = hash_be_hex_to_int(existing.hash_be_hex) if existing else None
    if not is_better_hash(candidate_int, existing_int):
        return None
    found_at = found_at_iso or datetime.now(timezone.utc).isoformat()
    record = BestHashRecord(
        hash_be_hex=hash_be_hex.strip().lower(),
        difficulty=difficulty_from_hash_int(candidate_int),
        nonce_hex=nonce_hex,
        job_id=job_id,
        nbits=nbits,
        network_difficulty_at_time=network_difficulty_at_time,
        found_at_iso=found_at,
    )
    records[network_id] = record
    save_best_hash_state(mode, records)
    return record