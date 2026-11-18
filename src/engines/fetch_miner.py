"""External miner download + SHA-256 pin + atomic installation (EXE cannot be modified)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# phase, received_bytes, total_bytes|None, detail message
ProgressCb = Callable[[str, int, Optional[int], str], None]

_LOCK_PATH = Path(__file__).resolve().parents[2] / "third_party" / "miners.lock.json"


def load_lock() -> dict[str, Any]:
    """Return pinned miner catalog. Empty dict if lock file is missing (native-only install)."""
    if not _LOCK_PATH.is_file():
        log.warning("miners.lock.json missing at %s — external miners unavailable", _LOCK_PATH)
        return {}
    raw = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("miners.lock.json invalid.")
    return raw


def miner_install_dir(miner_id: str, version: str) -> Path:
    from app_meta import APP_DATA_DIRNAME, LEGACY_APP_DATA_DIRNAMES

    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    primary = base / APP_DATA_DIRNAME / "miners" / miner_id / version
    if primary.is_dir():
        return primary
    # Use the legacy path to avoid re-downloading from the previous installation
    for legacy in LEGACY_APP_DATA_DIRNAMES:
        cand = base / legacy / "miners" / miner_id / version
        if cand.is_dir():
            return cand
    return primary


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _find_zip_member(zf: zipfile.ZipFile, exe_rel: str) -> str:
    """Explicitly select the expected archive member; don't rely on the first name found at random."""
    names = [n for n in zf.namelist() if not n.endswith("/")]
    norm_rel = exe_rel.replace("\\", "/").lstrip("/")
    # Full relative path
    for n in names:
        if n.replace("\\", "/") == norm_rel:
            return n
    # Subfolder in the zip root: …/exe_rel
    suffix = "/" + Path(norm_rel).name
    exact_name = Path(norm_rel).name
    candidates = [
        n for n in names if n.replace("\\", "/").endswith(suffix) or Path(n).name == exact_name
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise RuntimeError(f"No exe in ZIP: {exe_rel}")
    # Multiple identical names → only single-level / exact match
    preferred = [c for c in candidates if c.replace("\\", "/").endswith("/" + norm_rel) or c == norm_rel]
    if len(preferred) == 1:
        return preferred[0]
    raise RuntimeError(
        f"Multiple {exact_name} in ZIP; expected path ambiguous: {candidates[:5]}"
    )


def _safe_extract_member(zf: zipfile.ZipFile, member: str, dest_dir: Path) -> Path:
    dest_root = dest_dir.resolve()
    # Member path zip-slip check
    target = (dest_dir / member).resolve()
    if not str(target).startswith(str(dest_root) + os.sep) and target != dest_root:
        # Write in plain text with only the file name
        if ".." in member.replace("\\", "/").split("/"):
            raise RuntimeError(f"Zip slip reddedildi: {member}")
        target = (dest_dir / Path(member).name).resolve()
        if not str(target).startswith(str(dest_root)):
            raise RuntimeError(f"Zip slip reddedildi: {member}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member, "r") as src, target.open("wb") as out:
        shutil.copyfileobj(src, out)
    return target


def _verify_exe_matches_zip(zf: zipfile.ZipFile, member: str, exe_path: Path) -> None:
    raw = zf.read(member)
    if not exe_path.is_file():
        raise RuntimeError(f"Kurulu exe yok: {exe_path}")
    on_disk = exe_path.read_bytes()
    if _sha256_bytes(raw) != _sha256_bytes(on_disk):
        raise RuntimeError(
            f"Executable does not match archive (may have been modified): {exe_path.name}"
        )


_ALLOWED_HOST_SUFFIXES = (
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)


def _assert_official_download_url(url: str) -> None:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if not any(host == s or host.endswith("." + s) for s in _ALLOWED_HOST_SUFFIXES):
        raise RuntimeError(
            f"Refusing download from non-official host: {host or url!r}. "
            "Only pinned official GitHub release URLs are allowed."
        )


def ensure_miner(
    miner_id: str,
    *,
    reverify: bool = True,
    require_consent: bool = True,
    progress: ProgressCb | None = None,
) -> Path:
    """
    Atomic install from a ZIP whose SHA matches the lock file.
    Downloaded bytes are not reshaped to match the lock hash.
    New downloads require miner_download_consent in settings (unless require_consent=False).
    progress(phase, received, total, detail) is optional UI feedback.
    """
    def _prog(phase: str, received: int = 0, total: Optional[int] = None, detail: str = "") -> None:
        if progress is not None:
            try:
                progress(phase, received, total, detail)
            except Exception:
                log.debug("progress callback failed", exc_info=True)

    lock = load_lock()
    entry = lock.get(miner_id)
    if not isinstance(entry, dict):
        raise KeyError(f"not in miners.lock: {miner_id}")
    version = str(entry["version"])
    url = str(entry["url"])
    expect = str(entry["sha256"]).lower()
    asset = str(entry["asset"])
    exe_rel = str(entry.get("exe_relpath") or "xmrig.exe")
    _assert_official_download_url(url)

    base_dir = miner_install_dir(miner_id, version)
    base_dir.mkdir(parents=True, exist_ok=True)
    zip_path = base_dir / asset
    # Verified installation root — linked to zip SHA (old dirty EXE not used)
    install_dir = base_dir / f"verified_{expect[:16]}"
    marker = install_dir / ".ebf4000_verified"
    legacy_marker = install_dir / ".soloblockstrike_verified"
    exe_name = Path(exe_rel).name

    need_download = True
    if zip_path.is_file():
        _prog("check", 0, None, f"Checking existing {asset}…")
        got = _sha256_file(zip_path).lower()
        if got == expect:
            need_download = False
        else:
            zip_path.unlink(missing_ok=True)

    if need_download:
        if require_consent:
            from engines.miner_catalog import load_consent_from_settings

            if not load_consent_from_settings():
                raise RuntimeError(
                    f"Download of {miner_id} blocked: user consent required. "
                    "Accept the miner download consent dialog, then try again."
                )
        from app_meta import APP_USER_AGENT

        log.info("Downloading miner from official URL: %s", url)
        _prog("download", 0, None, f"Connecting to official release…\n{url}")
        tmp_zip = zip_path.with_suffix(".part")
        req = urllib.request.Request(url, headers={"User-Agent": APP_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp, tmp_zip.open("wb") as out:
                total_hdr = resp.headers.get("Content-Length")
                total_n = int(total_hdr) if total_hdr and str(total_hdr).isdigit() else None
                received = 0
                _prog("download", 0, total_n, f"Downloading {asset}…")
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    received += len(chunk)
                    _prog("download", received, total_n, f"Downloading {asset}…")
        except Exception:
            tmp_zip.unlink(missing_ok=True)
            raise
        _prog("verify", 0, None, "Verifying SHA-256 checksum…")
        got = _sha256_file(tmp_zip).lower()
        if got != expect:
            tmp_zip.unlink(missing_ok=True)
            raise RuntimeError(
                f"{miner_id} SHA-256 mismatch: expected={expect} got={got}"
            )
        tmp_zip.replace(zip_path)
        try:
            from engines.windows_security import clear_zone_identifier

            clear_zone_identifier(zip_path)
        except Exception:
            log.debug("zip MOTW cleanup skipped", exc_info=True)

    _prog("verify", 0, None, f"Verifying {asset}…")
    got = _sha256_file(zip_path).lower()
    if got != expect:
        zip_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"{miner_id} SHA-256 mismatch: expected={expect} got={got}"
        )

    with zipfile.ZipFile(zip_path, "r") as zf:
        member = _find_zip_member(zf, exe_rel)
        exe_path = install_dir / Path(member).name
        def _marker_ok() -> bool:
            for m in (marker, legacy_marker):
                if m.is_file() and m.read_text(encoding="utf-8").strip() == expect:
                    return True
            return False

        # Current setup: marker + byte match
        if reverify and _marker_ok() and exe_path.is_file():
            try:
                _verify_exe_matches_zip(zf, member, exe_path)
                try:
                    from engines.windows_security import clear_zone_identifier

                    clear_zone_identifier(exe_path)
                except Exception:
                    pass
                _prog("done", 1, 1, f"{exe_name} ready")
                return exe_path.resolve()
            except RuntimeError:
                log.warning("Installed EXE is corrupted — re-extracting: %s", exe_path)
                shutil.rmtree(install_dir, ignore_errors=True)

        if not reverify and exe_path.is_file() and (marker.is_file() or legacy_marker.is_file()):
            _prog("done", 1, 1, f"{exe_name} ready")
            return exe_path.resolve()

        # Atomic: move to temp → verify → replace
        _prog("extract", 0, None, f"Extracting {exe_name}…")
        with tempfile.TemporaryDirectory(dir=str(base_dir)) as tmp:
            tmp_root = Path(tmp)
            out_exe = _safe_extract_member(zf, member, tmp_root)
            _verify_exe_matches_zip(zf, member, out_exe)
            if install_dir.exists():
                shutil.rmtree(install_dir, ignore_errors=True)
            install_dir.mkdir(parents=True, exist_ok=True)
            final = install_dir / out_exe.name
            shutil.move(str(out_exe), str(final))
            try:
                from engines.windows_security import clear_zone_identifier

                clear_zone_identifier(final)
            except Exception:
                log.debug("exe MOTW cleanup skipped", exc_info=True)
            marker.write_text(expect, encoding="utf-8")
            _prog("done", 1, 1, f"{exe_name} installed")
            return final.resolve()
