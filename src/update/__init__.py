"""GitHub Releases auto-update (ZIP + minisign). Does not touch mining engines."""

from __future__ import annotations

from update.semver import parse_version, version_gt
from update.paths import install_root, updates_dir

__all__ = [
    "parse_version",
    "version_gt",
    "install_root",
    "updates_dir",
]
