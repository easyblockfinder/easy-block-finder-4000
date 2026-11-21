"""XMRig localhost HTTP control — Bearer token only; no remote bind."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Optional

from app_meta import APP_USER_AGENT

log = logging.getLogger(__name__)


def xmrig_json_rpc(
    *,
    http_port: int,
    http_token: str,
    method: str,
    timeout_s: float = 3.0,
) -> dict[str, Any]:
    """
    POST http://127.0.0.1:{port}/json_rpc with Authorization Bearer.
    Used for pause/resume (XMRig 6.x unrestricted HTTP).
    """
    port = int(http_port)
    token = (http_token or "").strip()
    if port < 1 or port > 65535:
        raise ValueError("Invalid XMRig HTTP port.")
    if not token:
        raise ValueError("XMRig HTTP token required.")
    url = f"http://127.0.0.1:{port}/json_rpc"
    body = json.dumps({"method": str(method), "id": 1}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": APP_USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw) if raw else {}
    return data if isinstance(data, dict) else {}


def pause_xmrig(*, http_port: int, http_token: str) -> bool:
    try:
        data = xmrig_json_rpc(
            http_port=http_port, http_token=http_token, method="pause"
        )
        if data.get("error"):
            log.warning("XMRig pause error: %s", data.get("error"))
            return False
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("XMRig pause failed: %s", exc)
        return False


def resume_xmrig(*, http_port: int, http_token: str) -> bool:
    try:
        data = xmrig_json_rpc(
            http_port=http_port, http_token=http_token, method="resume"
        )
        if data.get("error"):
            log.warning("XMRig resume error: %s", data.get("error"))
            return False
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("XMRig resume failed: %s", exc)
        return False


def probe_pause_resume(*, http_port: int, http_token: str) -> bool:
    """Best-effort: resume is idempotent; success means control channel works."""
    return resume_xmrig(http_port=http_port, http_token=http_token)
