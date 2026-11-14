"""Parse / verify SHA256SUMS manifests (GNU coreutils style)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_LINE_RE = re.compile(
    r"^(?P<hash>[0-9a-fA-F]{64})[ \t]+(?P<binary>\*)?(?P<name>.+)$"
)


class ChecksumError(Exception):
    pass


def parse_sha256sums(text: str) -> dict[str, str]:
    """Map basename -> lowercase hex digest."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            raise ChecksumError(f"Bad SHA256SUMS line: {line!r}")
        name = Path(m.group("name").strip()).name
        out[name] = m.group("hash").lower()
    if not out:
        raise ChecksumError("SHA256SUMS is empty")
    return out


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def verify_file_digest(path: Path, expected_hex: str) -> None:
    got = sha256_file(path)
    if got.lower() != expected_hex.lower():
        raise ChecksumError(
            f"SHA-256 mismatch for {path.name}: expected {expected_hex}, got {got}"
        )
