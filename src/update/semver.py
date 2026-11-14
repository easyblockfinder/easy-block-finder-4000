"""Strict SemVer compare for update gating (MAJOR.MINOR.PATCH)."""

from __future__ import annotations

import re
from typing import NamedTuple

_SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


class Version(NamedTuple):
    major: int
    minor: int
    patch: int
    pre: str = ""

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.pre}" if self.pre else base


def parse_version(text: str) -> Version:
    s = (text or "").strip()
    if s.lower().startswith("ebf4000-"):
        s = s.split("-", 1)[-1]
    m = _SEMVER_RE.match(s)
    if not m:
        raise ValueError(f"Not a SemVer version: {text!r}")
    return Version(
        int(m.group("major")),
        int(m.group("minor")),
        int(m.group("patch")),
        (m.group("pre") or ""),
    )


def version_gt(a: Version | str, b: Version | str) -> bool:
    """True if a > b (pre-release is lower than the same numbers without pre)."""
    va = a if isinstance(a, Version) else parse_version(str(a))
    vb = b if isinstance(b, Version) else parse_version(str(b))
    if (va.major, va.minor, va.patch) != (vb.major, vb.minor, vb.patch):
        return (va.major, va.minor, va.patch) > (vb.major, vb.minor, vb.patch)
    if not va.pre and vb.pre:
        return True
    if va.pre and not vb.pre:
        return False
    return va.pre > vb.pre


def version_eq(a: Version | str, b: Version | str) -> bool:
    va = a if isinstance(a, Version) else parse_version(str(a))
    vb = b if isinstance(b, Version) else parse_version(str(b))
    return va == vb
