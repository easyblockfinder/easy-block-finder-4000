"""Safe ZIP extraction — block path traversal and absolute paths."""

from __future__ import annotations

import zipfile
from pathlib import Path


class UnsafeZipError(Exception):
    pass


def _is_within(directory: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def safe_extract(zip_path: Path, dest_dir: Path) -> Path:
    """
    Extract zip into dest_dir.
    Returns the content root (strips a single top-level folder if present).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if n and not n.endswith("/")]
        if not names:
            raise UnsafeZipError("ZIP has no files")
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or re_abs_drive(name):
                raise UnsafeZipError(f"Absolute path in ZIP: {name}")
            if ".." in Path(name).parts:
                raise UnsafeZipError(f"Path traversal in ZIP: {name}")
            target = (dest_dir / name).resolve()
            if not _is_within(dest_dir, target):
                raise UnsafeZipError(f"ZIP entry escapes destination: {name}")
        zf.extractall(dest_dir)

    # If zip has a single top-level directory, use that as content root
    children = [p for p in dest_dir.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return dest_dir


def re_abs_drive(name: str) -> bool:
    return len(name) >= 2 and name[1] == ":"
