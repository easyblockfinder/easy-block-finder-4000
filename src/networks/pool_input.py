"""Validate and sanitize user pool connection fields (no shell injection)."""

from __future__ import annotations

import re
from typing import Optional

# Hostname / DNS label or IPv4 — no spaces, no shell metacharacters.
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?$"
    r"|^(?:\d{1,3}\.){3}\d{1,3}$"
)
_WORKER_RE = re.compile(r"^[A-Za-z0-9_.\-]{0,64}$")
_ALLOWED_USERNAME_FORMATS = frozenset(
    {
        "{wallet}",
        "{address}",
        "solo:{wallet}",
        "solo:{address}",
        "{wallet}.{worker}",
        "{address}.{worker}",
        "{worker}",
    }
)


def sanitize_host(raw: str) -> str:
    """Strip URL scheme/path; return bare host or raise ValueError."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("Pool hostname is required.")
    # Reject injection-prone characters early.
    if any(c in s for c in (" ", "\t", "\n", ";", "|", "&", "`", "$", "(", ")", "<", ">", "\"", "'", "\\")):
        raise ValueError("Pool hostname contains invalid characters.")
    lower = s.lower()
    for prefix in ("stratum+ssl://", "stratum+tcp://", "stratum://", "ssl://", "tcp://", "https://", "http://"):
        if lower.startswith(prefix):
            s = s[len(prefix) :]
            lower = s.lower()
            break
    # Drop path / userinfo if pasted as URL
    if "@" in s:
        s = s.split("@", 1)[-1]
    if "/" in s:
        s = s.split("/", 1)[0]
    if "?" in s:
        s = s.split("?", 1)[0]
    if ":" in s and not _looks_like_ipv6(s):
        # host:port paste → take host only (port is a separate field)
        host_part, maybe_port = s.rsplit(":", 1)
        if maybe_port.isdigit():
            s = host_part
    s = s.strip().strip("[]")
    if not s or not _HOST_RE.match(s):
        raise ValueError("Pool hostname is not a valid DNS name or IPv4 address.")
    return s


def _looks_like_ipv6(s: str) -> bool:
    return s.startswith("[") or (s.count(":") >= 2)


def parse_port(raw: object) -> int:
    try:
        port = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("Pool port must be an integer.") from exc
    if port < 1 or port > 65535:
        raise ValueError("Pool port must be between 1 and 65535.")
    return port


def validate_worker(raw: str) -> str:
    s = (raw or "").strip()
    if not _WORKER_RE.match(s):
        raise ValueError(
            "Worker name may only contain letters, digits, underscore, dot, and hyphen."
        )
    return s


def validate_username_format(raw: str) -> str:
    s = (raw or "").strip() or "{wallet}"
    if s not in _ALLOWED_USERNAME_FORMATS:
        raise ValueError(
            "Unsupported username format. Use a preset such as {wallet}, "
            "solo:{wallet}, or {wallet}.{worker}."
        )
    return s


def validate_password(raw: str) -> str:
    s = raw if raw is not None else "x"
    if not isinstance(s, str):
        raise ValueError("Password must be text.")
    if len(s) > 128:
        raise ValueError("Password is too long.")
    if any(c in s for c in ("\n", "\r", "\x00")):
        raise ValueError("Password contains invalid characters.")
    return s or "x"


def mask_secret(value: str, *, keep: int = 0) -> str:
    """Mask passwords for logs."""
    if not value:
        return ""
    if keep <= 0:
        return "***"
    if len(value) <= keep:
        return "***"
    return value[:keep] + "***"


def safe_pool_log_fields(
    *,
    host: str,
    port: int,
    transport: str,
    username: str,
    password: str,
) -> dict[str, object]:
    return {
        "host": host,
        "port": port,
        "transport": transport,
        "username": username,
        "password": mask_secret(password),
    }
