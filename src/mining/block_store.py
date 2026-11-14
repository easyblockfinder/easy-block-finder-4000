"""Permanent recording of block candidates and block explorer status tracking."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional  # noqa: F401 — Any used in _http_json

log = logging.getLogger(__name__)

STATUS_CANDIDATE = "aday_bulundu"
STATUS_POOL = "pool_yaniti_alindi"
STATUS_PENDING_VERIFY = "dogrulama_bekleniyor"
STATUS_CONFIRMED = "ana_zincirde_dogrulandi"
STATUS_ORPHAN = "zincir_disinda"
STATUS_TEST = "test_modu"
NETWORK_UNKNOWN = "unknown"

EXPLORER_URL = "https://blockstream.info/api/block/{hash}"
EXPLORER_STATUS_URL = "https://blockstream.info/api/block/{hash}/status"


def _app_data_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def _default_user_store_file() -> Path:
    from app_meta import APP_DATA_DIRNAME

    return _app_data_root() / APP_DATA_DIRNAME / "block_candidates.json"


def _legacy_user_store_files() -> list[Path]:
    from app_meta import LEGACY_APP_DATA_DIRNAMES

    return [_app_data_root() / name / "block_candidates.json" for name in LEGACY_APP_DATA_DIRNAMES]


def _legacy_user_store_file() -> Path:
    files = _legacy_user_store_files()
    return files[0] if files else _app_data_root() / "BTCHunter" / "block_candidates.json"


def _store_path() -> Path:
    # Tests are removed from the real user file with EBF4000_BLOCK_STORE_DIR / old env
    override = (
        os.environ.get("EBF4000_BLOCK_STORE_DIR")
        or os.environ.get("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR")
        or os.environ.get("BTCHUNTER_BLOCK_STORE_DIR")
    )
    if override:
        folder = Path(override)
    else:
        folder = _default_user_store_file().parent
        # Copy the old block_candidates once if the new folder is empty
        target = folder / "block_candidates.json"
        if not target.is_file():
            for legacy in _legacy_user_store_files():
                if legacy.is_file():
                    try:
                        folder.mkdir(parents=True, exist_ok=True)
                        import shutil

                        shutil.copy2(legacy, target)
                    except OSError:
                        pass
                    break
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "block_candidates.json"


def _guard_against_pytest_user_file(path: Path) -> None:
    """Under pytest, the actual user block_candidates.json is prohibited."""
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        return
    banned = {_default_user_store_file().resolve()}
    banned.update(p.resolve() for p in _legacy_user_store_files())
    try:
        if path.resolve() in banned:
            raise RuntimeError(
                "Tests cannot write to the real user block_candidates.json; "
                "use tmp_path / EBF4000_BLOCK_STORE_DIR."
            )
    except FileNotFoundError:
        posix = path.as_posix()
        if (
            posix.endswith("EasyBlockFinder4000/block_candidates.json")
            or posix.endswith("SoloBlockStrike/block_candidates.json")
            or posix.endswith("BTCHunter/block_candidates.json")
        ) and not (
            os.environ.get("EBF4000_BLOCK_STORE_DIR")
            or os.environ.get("SOLOBLOCKSTRIKE_BLOCK_STORE_DIR")
            or os.environ.get("BTCHUNTER_BLOCK_STORE_DIR")
        ):
            raise RuntimeError(
                "Tests cannot write to the real user block_candidates.json."
            )


class BlockCandidateStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else _store_path()
        _guard_against_pytest_user_file(self.path)
        self._lock = threading.Lock()
        self._queue: list[tuple[str, dict]] = []
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._last_error: Optional[str] = None
        self._flushing = False
        self._idle = threading.Event()
        self._idle.set()
        self._thread: Optional[threading.Thread] = None
        self.ensure_writer()

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def ensure_writer(self) -> None:
        """If there is no writer after Stop→Start, restart (no zombie pair writer)."""
        t = self._thread
        if t is not None and t.is_alive():
            if not self._stop.is_set():
                return
            # Stop requested, but the thread is not dead yet — do not clear the shared stop
            t.join(timeout=2.0)
            if t.is_alive():
                log.warning(
                    "block-store still closing — new writer deferred (reference kept)"
                )
                return
            self._thread = None
        elif t is not None and not t.is_alive():
            self._thread = None
        # New Event: Reopen the zombie by sharing the old stop flag
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._writer_loop, name="block-store", daemon=True
        )
        self._thread.start()

    def load(
        self,
        network_id: Optional[str] = None,
        *,
        include_unknown: bool = False,
    ) -> list[dict]:
        path = self.path
        if not path.is_file() and path == _store_path():
            legacy = _legacy_user_store_file()
            if legacy.is_file():
                path = legacy
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                items = [migrate_block_record(x) for x in raw if isinstance(x, dict)]
                if network_id:
                    nid = str(network_id).strip().lower()
                    # include_unknown: Show unknown legacy records in the UI (no explorer)
                    out = []
                    for x in items:
                        xn = str(x.get("network_id") or "").lower()
                        if xn == nid or (
                            include_unknown and xn == NETWORK_UNKNOWN
                        ):
                            out.append(x)
                    return out
                return items
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            self._last_error = f"Block candidate load error: {exc}"
            log.warning("%s", self._last_error)
        return []

    def enqueue_upsert(self, record: dict) -> None:
        """Called from the critical path — does not perform disk I/O."""
        self.ensure_writer()
        with self._lock:
            self._queue.append(("upsert", dict(record)))
            self._idle.clear()
        self._wake.set()

    def drain(self, timeout_s: float = 5.0) -> Optional[str]:
        """
        Drain the queue and wait for in-flight disk writes to finish.
        On timeout no second flush is started; raises an explicit timeout error.
        """
        deadline = time.time() + timeout_s
        self._wake.set()
        while time.time() < deadline:
            with self._lock:
                idle = (not self._queue) and (not self._flushing)
            if idle:
                if self._idle.wait(timeout=0.2):
                    with self._lock:
                        if (not self._queue) and (not self._flushing):
                            return self._last_error
            else:
                self._wake.set()
            time.sleep(0.02)

        with self._lock:
            still_busy = bool(self._queue) or bool(self._flushing)
        if still_busy:
            self._last_error = (
                f"Block candidate drain timeout ({timeout_s:.1f}s); "
                "write in progress or queue full — second flush not started."
            )
            log.warning("%s", self._last_error)
            return self._last_error
        return self._last_error

    def stop(self) -> None:
        err = self.drain(timeout_s=4.0)
        if err:
            log.warning("Block record at closing: %s", err)
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t is not None:
            t.join(timeout=3)
            if t.is_alive():
                # Timeout — keep the reference; ensure_writer shouldn't clear the common event
                log.warning("block-store join timeout — referans korunuyor")
                return
        self._thread = None

    def _flush(self, batch: list[tuple[str, dict]], *, already_marked: bool = False) -> None:
        if not batch:
            return
        if not already_marked:
            with self._lock:
                self._flushing = True
                self._idle.clear()
        try:
            try:
                items = self.load()
                by_key = {self._key(x): x for x in items}
                for _, rec in batch:
                    by_key[self._key(rec)] = rec
                merged = sorted(
                    by_key.values(),
                    key=lambda r: r.get("found_at") or r.get("time") or "",
                    reverse=True,
                )[:200]
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(merged, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                tmp.replace(self.path)
                self._last_error = None
            except OSError as exc:
                self._last_error = f"Block candidate save error: {exc}"
                log.warning("%s", self._last_error)
        finally:
            with self._lock:
                self._flushing = False
                if not self._queue:
                    self._idle.set()
                else:
                    self._idle.clear()

    def _writer_loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            batch: list[tuple[str, dict]] = []
            with self._lock:
                if self._queue:
                    batch = self._queue[:]
                    self._queue.clear()
                    # To prevent the drain from thinking it's idle before the queue is emptied and the flush starts
                    self._flushing = True
                    self._idle.clear()
            if batch:
                self._flush(batch, already_marked=True)
            else:
                with self._lock:
                    if not self._flushing and not self._queue:
                        self._idle.set()

    @staticmethod
    def _key(rec: dict) -> str:
        nid = str(rec.get("network_id") or NETWORK_UNKNOWN).strip().lower()
        h = str(rec.get("hash") or "").strip().lower()
        if h:
            return f"{nid}:{h}"
        return (
            f"{nid}|{rec.get('job_id')}|{rec.get('nonce_hex')}|{rec.get('extranonce2')}"
        )


def _legacy_ambiguous_base58(payout: str) -> bool:
    """1…/3… legacy — BTC and BCH are common; not considered proof of network."""
    p = (payout or "").strip()
    if len(p) < 26:
        return False
    if p.lower().startswith("bitcoincash:"):
        return False
    return p[0] in ("1", "3")


def migrate_block_record(rec: dict) -> dict:
    """Add network_id to old records; withdraw BTC from 1/3 addresses; keep the unknown as unknown."""
    out = dict(rec)
    origin = str(out.get("store_origin") or out.get("app") or "").lower()
    payout = str(out.get("payout_address") or "")
    trusted_btc = out.get("legacy_btc_hunter") is True or "btchunter" in origin

    nid = out.get("network_id")
    if isinstance(nid, str) and nid.strip():
        out["network_id"] = nid.strip().lower()
        # Previous incorrect migration: inferred + indefinite 1/3 → unknown
        if (
            out["network_id"] == "btc"
            and out.get("network_id_inferred") is True
            and not trusted_btc
            and _legacy_ambiguous_base58(payout)
            and not payout.startswith("bc1")
        ):
            out["network_id"] = NETWORK_UNKNOWN
            out["network_id_inferred"] = False
        return out

    if trusted_btc:
        out["network_id"] = "btc"
        out["network_id_inferred"] = True
        return out
    if payout.startswith("bc1"):
        out["network_id"] = "btc"
        out["network_id_inferred"] = True
        return out
    if payout.lower().startswith("bitcoincash:"):
        out["network_id"] = "bch"
        out["network_id_inferred"] = True
        return out
    # 1…/3… belirsiz — BTC varsayma
    out["network_id"] = NETWORK_UNKNOWN
    out["network_id_inferred"] = False
    return out


class ExplorerTracker:
    """Interval walker query for block hash. 404 = not a definitive rejection."""

    def __init__(
        self,
        on_update: Optional[Callable[[dict], None]] = None,
        interval_s: float = 120.0,
        *,
        status_url: str = EXPLORER_STATUS_URL,
        block_url: str = EXPLORER_URL,
        kind: str = "blockstream",
    ) -> None:
        self.on_update = on_update
        self.interval_s = interval_s
        self.status_url = status_url or EXPLORER_STATUS_URL
        self.block_url = block_url or EXPLORER_URL
        self.kind = kind or "blockstream"
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._watch: dict[str, dict] = {}

    def configure(
        self,
        *,
        status_url: str = "",
        block_url: str = "",
        kind: str = "blockstream",
    ) -> None:
        """Active UI network default — does not change the endpoints of existing _watch records."""
        self.status_url = status_url or EXPLORER_STATUS_URL
        self.block_url = block_url or EXPLORER_URL
        self.kind = kind or "none"

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        t = self._thread
        if t is not None and t.is_alive():
            if not self._stop.is_set():
                return
            # Stop requested, but the thread is not dead yet — wait a moment
            t.join(timeout=2.0)
            if t.is_alive():
                log.warning(
                    "Explorer still closing — new start deferred (reference kept)"
                )
                return
            self._thread = None
        elif t is not None and not t.is_alive():
            # Thread died after timeout — can be restarted
            self._thread = None
        # New Event: Reopen the zombie by sharing the old stop flag
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name="explorer-track", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=3)
            if t.is_alive():
                # Timeout — preserve reference; do not reopen the old thread with the common event
                log.warning("Explorer thread join timeout — referans korunuyor")
                return
        self._thread = None

    @staticmethod
    def _watch_key(record: dict) -> str:
        nid = str(record.get("network_id") or NETWORK_UNKNOWN).strip().lower()
        h = str(record.get("hash") or "").strip().lower()
        return f"{nid}:{h}"

    @staticmethod
    def _endpoints_for_network(network_id: str) -> tuple[str, str, str]:
        """(status_url, block_url, kind) — based on the registry network; independent of the UI configuration."""
        try:
            from networks.profiles import get_profile

            p = get_profile(network_id)
            kind = (p.explorer_kind or "none").strip() or "none"
            return (
                p.explorer_status_url or "",
                p.explorer_block_url or "",
                kind,
            )
        except Exception:
            return "", "", "none"

    def watch(self, record: dict) -> None:
        h = str(record.get("hash") or "")
        if not h or record.get("test_mode"):
            return
        nid = str(record.get("network_id") or "").strip().lower()
        if nid in ("", NETWORK_UNKNOWN):
            # Network unknown — no automatic explorer
            return
        status_url, block_url, kind = self._endpoints_for_network(nid)
        if kind in ("", "none") or not status_url:
            return
        stored = dict(record)
        stored["_explorer_status_url"] = status_url
        stored["_explorer_block_url"] = block_url
        stored["_explorer_kind"] = kind
        with self._lock:
            self._watch[self._watch_key(record)] = stored
        self.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                items = list(self._watch.values())
            for rec in items:
                if self._stop.is_set():
                    break
                self._probe(rec)
            self._stop.wait(self.interval_s)

    def _http_json(self, url: str) -> Any:
        from app_meta import APP_USER_AGENT

        req = urllib.request.Request(url, headers={"User-Agent": APP_USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _probe(self, rec: dict) -> None:
        h = str(rec.get("hash") or "")
        if not h:
            return
        kind = str(rec.get("_explorer_kind") or "").strip()
        status_url = str(rec.get("_explorer_status_url") or "")
        block_url = str(rec.get("_explorer_block_url") or "")
        if not kind or not status_url:
            nid = str(rec.get("network_id") or "").strip().lower()
            status_url, block_url, kind = self._endpoints_for_network(nid)
        if kind in ("", "none") or not status_url:
            return
        if kind == "blockchair_bch":
            self._probe_blockchair(rec, h, status_url=status_url)
            return
        try:
            status = self._http_json(status_url.format(hash=h))
            try:
                block = self._http_json(block_url.format(hash=h)) if block_url else {}
            except Exception:
                block = {}
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                upd = {
                    **rec,
                    "chain_status": STATUS_PENDING_VERIFY,
                    "chain_detail": "Explorer 404 (may be temporary; will retry)",
                    "explorer_checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                self._emit(upd)
                return
            upd = {
                **rec,
                "chain_status": STATUS_PENDING_VERIFY,
                "chain_detail": f"Gezgin HTTP {exc.code}",
                "explorer_checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._emit(upd)
            return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            upd = {
                **rec,
                "chain_status": STATUS_PENDING_VERIFY,
                "chain_detail": f"Explorer access error: {exc}",
                "explorer_checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._emit(upd)
            return

        height = status.get("height")
        if height is None:
            height = block.get("height")
        in_best = status.get("in_best_chain")
        if in_best is True:
            chain_status = STATUS_CONFIRMED
            detail = f"Ana zincir height={height}"
        elif in_best is False:
            chain_status = STATUS_ORPHAN
            detail = f"Off-chain height={height}"
        else:
            chain_status = STATUS_PENDING_VERIFY
            detail = f"Ambiguous explorer response height={height}"

        upd = {
            **rec,
            "chain_status": chain_status,
            "chain_height": height,
            "chain_detail": detail,
            "explorer_checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "explorer_raw_status": status,
        }
        self._emit(upd)

        if chain_status == STATUS_CONFIRMED:
            with self._lock:
                self._watch.pop(self._watch_key(rec), None)

    def _probe_blockchair(self, rec: dict, h: str, *, status_url: str = "") -> None:
        url = status_url or str(rec.get("_explorer_status_url") or self.status_url)
        try:
            data = self._http_json(url.format(hash=h))
        except urllib.error.HTTPError as exc:
            detail = (
                "Explorer 404 (may be temporary)"
                if exc.code == 404
                else f"Blockchair HTTP {exc.code}"
            )
            self._emit(
                {
                    **rec,
                    "chain_status": STATUS_PENDING_VERIFY,
                    "chain_detail": detail,
                    "explorer_checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            self._emit(
                {
                    **rec,
                    "chain_status": STATUS_PENDING_VERIFY,
                    "chain_detail": f"Blockchair access error: {exc}",
                    "explorer_checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            return
        blocks = (data or {}).get("data") or {}
        entry = blocks.get(h) or blocks.get(h.lower()) or {}
        block = entry.get("block") if isinstance(entry, dict) else {}
        if not isinstance(block, dict):
            block = {}
        height = block.get("id") or block.get("height")
        if block:
            chain_status = STATUS_CONFIRMED
            detail = f"Blockchair BCH record height={height}"
        else:
            chain_status = STATUS_PENDING_VERIFY
            detail = "Blockchair: block not found / unknown"
        self._emit(
            {
                **rec,
                "chain_status": chain_status,
                "chain_height": height,
                "chain_detail": detail,
                "explorer_checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "explorer_raw_status": {"kind": "blockchair_bch", "found": bool(block)},
            }
        )
        if chain_status == STATUS_CONFIRMED:
            with self._lock:
                self._watch.pop(self._watch_key(rec), None)

    def _emit(self, rec: dict) -> None:
        key = self._watch_key(rec)
        with self._lock:
            if key in self._watch:
                self._watch[key] = rec
        if self.on_update:
            try:
                self.on_update(rec)
            except Exception:
                log.exception("explorer on_update")
