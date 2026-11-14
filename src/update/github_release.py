"""Fetch latest GitHub Release metadata (fail soft for the UI)."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from app_meta import APP_USER_AGENT
from update.trusted_keys import (
    GITHUB_API_LATEST,
    MANIFEST_NAME,
    MANIFEST_SIG_NAME,
    ZIP_ASSET_PREFIX,
    ZIP_ASSET_SUFFIX,
)


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    size: int


@dataclass(frozen=True)
class LatestRelease:
    tag: str
    name: str
    body: str
    html_url: str
    zip_asset: ReleaseAsset
    sums_asset: ReleaseAsset
    sig_asset: ReleaseAsset


class ReleaseLookupError(Exception):
    """Network / API / asset layout problems (non-fatal for the app)."""


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def fetch_json(url: str, *, timeout: float = 20.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": APP_USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            raw = resp.read()
            if resp.status == 403 and b"rate limit" in raw.lower():
                raise ReleaseLookupError("GitHub API rate limit exceeded")
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        if exc.code == 403 and "rate limit" in body.lower():
            raise ReleaseLookupError("GitHub API rate limit exceeded") from exc
        raise ReleaseLookupError(f"GitHub HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ReleaseLookupError(f"Network error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ReleaseLookupError("GitHub request timed out") from exc
    except json.JSONDecodeError as exc:
        raise ReleaseLookupError("Invalid JSON from GitHub") from exc


def _pick_asset(assets: list[dict[str, Any]], name: str) -> Optional[ReleaseAsset]:
    for a in assets:
        if str(a.get("name") or "") == name:
            return ReleaseAsset(
                name=name,
                url=str(a.get("browser_download_url") or ""),
                size=int(a.get("size") or 0),
            )
    return None


def _find_zip(assets: list[dict[str, Any]], tag: str) -> Optional[ReleaseAsset]:
    # Prefer exact EBF4000-v{semver}-windows.zip derived from tag
    tag_ver = tag.lstrip("vV")
    exact = f"{ZIP_ASSET_PREFIX}{tag_ver}{ZIP_ASSET_SUFFIX}"
    hit = _pick_asset(assets, exact)
    if hit:
        return hit
    for a in assets:
        name = str(a.get("name") or "")
        if name.startswith(ZIP_ASSET_PREFIX) and name.endswith(ZIP_ASSET_SUFFIX):
            return ReleaseAsset(
                name=name,
                url=str(a.get("browser_download_url") or ""),
                size=int(a.get("size") or 0),
            )
    return None


def fetch_latest_release(api_url: str = GITHUB_API_LATEST) -> LatestRelease:
    data = fetch_json(api_url)
    if not isinstance(data, dict):
        raise ReleaseLookupError("Unexpected release payload")
    if data.get("draft") or data.get("prerelease"):
        # /releases/latest already skips these; guard anyway
        raise ReleaseLookupError("Latest release is draft/prerelease")
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise ReleaseLookupError("Release missing tag_name")
    assets = data.get("assets") or []
    if not isinstance(assets, list):
        raise ReleaseLookupError("Release assets missing")
    zip_asset = _find_zip(assets, tag)
    sums = _pick_asset(assets, MANIFEST_NAME)
    sig = _pick_asset(assets, MANIFEST_SIG_NAME)
    if not zip_asset or not zip_asset.url:
        raise ReleaseLookupError(
            f"No {ZIP_ASSET_PREFIX}*{ZIP_ASSET_SUFFIX} asset on latest release"
        )
    if not sums or not sums.url:
        raise ReleaseLookupError(f"Missing {MANIFEST_NAME} on latest release")
    if not sig or not sig.url:
        raise ReleaseLookupError(f"Missing {MANIFEST_SIG_NAME} on latest release")
    return LatestRelease(
        tag=tag,
        name=str(data.get("name") or tag),
        body=str(data.get("body") or ""),
        html_url=str(data.get("html_url") or ""),
        zip_asset=zip_asset,
        sums_asset=sums,
        sig_asset=sig,
    )


def download_file(
    url: str,
    dest: Path,
    *,
    progress: Callable[[int, Optional[int]], None] | None = None,
    timeout: float = 120.0,
) -> None:
    """Download URL to dest. progress(received: int, total: int|None)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": APP_USER_AGENT, "Accept": "application/octet-stream"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            total = resp.headers.get("Content-Length")
            total_n = int(total) if total and total.isdigit() else None
            received = 0
            with dest.open("wb") as out:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    received += len(chunk)
                    if progress is not None:
                        progress(received, total_n)
    except urllib.error.URLError as exc:
        raise ReleaseLookupError(f"Download failed: {exc}") from exc
