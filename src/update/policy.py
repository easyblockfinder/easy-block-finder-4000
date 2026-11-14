"""Update policy: version gate, trusted comment, no silent miner changes."""

from __future__ import annotations

import re
from pathlib import Path

from update.semver import Version, parse_version, version_gt
from update.trusted_keys import ZIP_ASSET_PREFIX, ZIP_ASSET_SUFFIX

_VERSION_IN_COMMENT = re.compile(
    r"(?:^|[\s;])version\s*[:=]\s*v?(?P<v>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)",
    re.I,
)
_ASSET_IN_COMMENT = re.compile(
    r"(?:^|[\s;])(?:asset|file)\s*[:=]\s*(?P<a>EBF4000-v[^\s;]+)",
    re.I,
)


class PolicyError(Exception):
    pass


def expected_zip_name(version: Version | str) -> str:
    v = version if isinstance(version, Version) else parse_version(str(version))
    return f"{ZIP_ASSET_PREFIX}{v}{ZIP_ASSET_SUFFIX}"


def assert_upgrade_allowed(current: str, remote_tag: str) -> Version:
    """Reject equal / older remote. Returns remote Version."""
    cur = parse_version(current)
    rem = parse_version(remote_tag)
    if not version_gt(rem, cur):
        raise PolicyError(
            f"Remote {rem} is not newer than installed {cur} (downgrade/equal blocked)"
        )
    return rem


def assert_manifest_identity(
    *,
    trusted_comment: str,
    remote_version: Version,
    zip_name: str,
) -> None:
    """
    Manifest signature trusted comment must not disagree with the release we intend.
    Optional keys: version=… asset=EBF4000-v…-windows.zip
    If present, they must match. If absent, zip filename must still match SemVer.
    """
    expect_zip = expected_zip_name(remote_version)
    if zip_name != expect_zip:
        # Allow zip name that embeds the same SemVer even if tag formatting differs
        try:
            embedded = parse_version(
                zip_name[len(ZIP_ASSET_PREFIX) : -len(ZIP_ASSET_SUFFIX)]
            )
        except ValueError as exc:
            raise PolicyError(f"ZIP asset name not recognized: {zip_name}") from exc
        if embedded != remote_version:
            raise PolicyError(
                f"ZIP asset {zip_name} does not match release version {remote_version}"
            )

    m_ver = _VERSION_IN_COMMENT.search(trusted_comment or "")
    if m_ver:
        commented = parse_version(m_ver.group("v"))
        if commented != remote_version:
            raise PolicyError(
                f"Signed trusted comment version {commented} != release {remote_version}"
            )

    m_asset = _ASSET_IN_COMMENT.search(trusted_comment or "")
    if m_asset:
        if Path(m_asset.group("a")).name != zip_name:
            raise PolicyError(
                f"Signed trusted comment asset mismatch: {m_asset.group('a')} vs {zip_name}"
            )


# Paths never replaced by the updater (relative to install root). Empty = none.
# AppData miners/settings live outside install_root by design.
PRESERVE_RELATIVE: frozenset[str] = frozenset()

# Globs under install root that the ZIP must not silently alter for third-party miners
FORBIDDEN_UPDATE_SUBTREES = (
    "miners/",  # if someone wrongly ships miners in the app zip
)
