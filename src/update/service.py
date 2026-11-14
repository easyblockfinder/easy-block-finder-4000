"""
Update check + verified download + handoff to external apply_update.

Never mutates the running install tree; never touches AppData miners/settings.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app_meta import APP_VERSION
from update.checksums import parse_sha256sums, verify_file_digest
from update.github_release import (
    LatestRelease,
    ReleaseLookupError,
    download_file,
    fetch_latest_release,
)
from update.minisign_verify import MinisignError, verify_file
from update.paths import install_root, staging_dir, updates_dir
from update.policy import (
    PolicyError,
    assert_manifest_identity,
    assert_upgrade_allowed,
    expected_zip_name,
)
from update.semver import parse_version, version_gt
from update.zip_safe import UnsafeZipError, safe_extract

ProgressCb = Callable[[str, int, Optional[int]], None]  # phase, received, total


@dataclass(frozen=True)
class UpdateOffer:
    current_version: str
    remote_version: str
    tag: str
    title: str
    notes: str
    html_url: str
    zip_name: str
    zip_size: int
    release: LatestRelease


@dataclass(frozen=True)
class PreparedUpdate:
    offer: UpdateOffer
    zip_path: Path
    payload_dir: Path
    stage_dir: Path
    job_path: Path


class UpdateError(Exception):
    pass


def check_for_update(
    *,
    current_version: str | None = None,
    api_url: str | None = None,
) -> Optional[UpdateOffer]:
    """
    Returns UpdateOffer if a newer signed-capable release exists.
    Returns None if up to date.
    Raises ReleaseLookupError / UpdateError on hard failures the UI may soft-handle.
    """
    cur = (current_version or APP_VERSION).strip()
    release = fetch_latest_release(api_url) if api_url else fetch_latest_release()
    try:
        remote_v = assert_upgrade_allowed(cur, release.tag)
    except PolicyError:
        return None
    return UpdateOffer(
        current_version=str(parse_version(cur)),
        remote_version=str(remote_v),
        tag=release.tag,
        title=release.name,
        notes=release.body,
        html_url=release.html_url,
        zip_name=release.zip_asset.name,
        zip_size=release.zip_asset.size,
        release=release,
    )


def prepare_update(
    offer: UpdateOffer,
    *,
    progress: ProgressCb | None = None,
) -> PreparedUpdate:
    """Download + minisign + sha256 + safe extract into staging. No install yet."""
    stage = staging_dir(offer.remote_version)
    # Clean previous extract for this version
    for child in list(stage.iterdir()):
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass

    rel = offer.release
    sums_path = stage / "SHA256SUMS"
    sig_path = stage / "SHA256SUMS.minisig"
    zip_path = stage / rel.zip_asset.name

    def _prog(phase: str):
        def inner(received: int, total: Optional[int]) -> None:
            if progress:
                progress(phase, received, total)

        return inner

    if progress:
        progress("manifest", 0, None)
    download_file(rel.sums_asset.url, sums_path, progress=_prog("manifest"))
    download_file(rel.sig_asset.url, sig_path, progress=_prog("signature"))
    download_file(rel.zip_asset.url, zip_path, progress=_prog("package"))

    try:
        trusted = verify_file(sums_path, sig_path)
    except MinisignError as exc:
        raise UpdateError(f"Signature verification failed — update aborted: {exc}") from exc

    try:
        assert_manifest_identity(
            trusted_comment=trusted,
            remote_version=parse_version(offer.remote_version),
            zip_name=rel.zip_asset.name,
        )
    except PolicyError as exc:
        raise UpdateError(str(exc)) from exc

    try:
        digests = parse_sha256sums(sums_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise UpdateError(f"SHA256SUMS parse failed: {exc}") from exc

    expect_name = rel.zip_asset.name
    if expect_name not in digests:
        # try canonical name
        canon = expected_zip_name(offer.remote_version)
        if canon in digests:
            expect_name = canon
        else:
            raise UpdateError(f"{rel.zip_asset.name} not listed in signed SHA256SUMS")

    try:
        verify_file_digest(zip_path, digests[expect_name])
    except Exception as exc:
        raise UpdateError(f"Package integrity check failed: {exc}") from exc

    extract_to = stage / "extracted"
    if extract_to.exists():
        shutil.rmtree(extract_to, ignore_errors=True)
    extract_to.mkdir(parents=True, exist_ok=True)
    try:
        payload = safe_extract(zip_path, extract_to)
    except UnsafeZipError as exc:
        raise UpdateError(f"Unsafe ZIP rejected: {exc}") from exc

    # Refuse zips that try to ship third-party miners into the app tree
    for bad in ("miners",):
        if (payload / bad).exists():
            raise UpdateError(
                "Update package contains a miners/ folder — refused "
                "(third-party miners are AppData-only after consent)"
            )

    if not (payload / "start.bat").is_file() and not (payload / "src" / "main.py").is_file():
        raise UpdateError("Update package missing start.bat / src/main.py")

    job = {
        "created": time.time(),
        "current_version": offer.current_version,
        "remote_version": offer.remote_version,
        "install_dir": str(install_root()),
        "payload_dir": str(payload),
        "backup_dir": str(updates_dir() / f"backup-{offer.current_version}"),
        "zip_name": rel.zip_asset.name,
        "pid": os.getpid(),
        "restart": {
            "cwd": str(install_root()),
            "bat": str(install_root() / "start.bat"),
        },
    }
    job_path = stage / "update_job.json"
    job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    return PreparedUpdate(
        offer=offer,
        zip_path=zip_path,
        payload_dir=payload,
        stage_dir=stage,
        job_path=job_path,
    )


def launch_external_updater(prepared: PreparedUpdate) -> None:
    """Start apply_update.py detached, then caller must exit the app."""
    root = install_root()
    # Prefer the NEW package's apply_update.py so restart/UI fixes ship on this update
    # (not only on the next one). Fall back to the installed copy if needed.
    staged = prepared.payload_dir / "scripts" / "apply_update.py"
    installed = root / "scripts" / "apply_update.py"
    if staged.is_file():
        apply_script = staged
    elif installed.is_file():
        apply_script = installed
    else:
        raise UpdateError("scripts/apply_update.py not found")

    python = sys.executable
    # Prefer console-less on Windows when pythonw available
    if python.lower().endswith("python.exe"):
        candidate = python[:-10] + "pythonw.exe"
        if Path(candidate).is_file():
            python = candidate

    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            getattr(os, "DETACHED_PROCESS", 0x00000008)
            | getattr(os, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | 0x08000000  # CREATE_NO_WINDOW
        )

    import subprocess

    subprocess.Popen(
        [
            python,
            str(apply_script),
            "--job",
            str(prepared.job_path),
        ],
        cwd=str(root),
        close_fds=True,
        creationflags=creationflags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def should_check_now(last_check_ts: float | None, interval_hours: float = 24.0) -> bool:
    if last_check_ts is None or last_check_ts <= 0:
        return True
    return (time.time() - float(last_check_ts)) >= float(interval_hours) * 3600.0


def is_newer(remote_tag: str, current: str | None = None) -> bool:
    try:
        return version_gt(remote_tag, current or APP_VERSION)
    except ValueError:
        return False
