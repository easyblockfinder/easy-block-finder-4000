"""Resolve default / preset / custom pool endpoints without changing defaults."""

from __future__ import annotations

from typing import Any, Optional

from networks.pool_input import (
    parse_port,
    sanitize_host,
    validate_password,
    validate_username_format,
    validate_worker,
)
from networks.pool_presets import get_preset
from networks.pool_types import (
    CustomPoolConfig,
    PoolKind,
    PoolMode,
    ResolvedPoolEndpoint,
    Transport,
)
from networks.pool_validation import default_validation_profile_id
from networks.profiles import get_profile, normalize_network_id


def _default_kind(network_id: str) -> PoolKind:
    # Built-in profiles are solo-oriented product paths.
    return "solo"


def resolve_default(network_id: str) -> ResolvedPoolEndpoint:
    nid = normalize_network_id(network_id)
    prof = get_profile(nid)
    return ResolvedPoolEndpoint(
        network_id=nid,
        mode="default",
        host=prof.stratum_host,
        port=int(prof.stratum_port),
        transport="tcp",
        username_format=prof.username_template.replace("{address}", "{wallet}"),
        worker="",
        password=prof.password or "x",
        pool_kind=_default_kind(nid),
        validation_profile_id=default_validation_profile_id(nid),
        preset_id=None,
        display_name=f"Default ({prof.stratum_host})",
        stats_url_template=prof.stats_url_template or "",
        notes=prof.pool_fee_note or "",
    )


def _parse_custom(raw: Any) -> CustomPoolConfig:
    if not isinstance(raw, dict):
        raise ValueError("Custom pool settings are invalid.")
    host = sanitize_host(str(raw.get("host") or ""))
    port = parse_port(raw.get("port"))
    transport_raw = str(raw.get("transport") or "tcp").strip().lower()
    if transport_raw not in ("tcp", "tls"):
        raise ValueError("Transport must be tcp or tls.")
    transport: Transport = "tls" if transport_raw == "tls" else "tcp"  # type: ignore[assignment]
    username_format = validate_username_format(str(raw.get("username_format") or "{wallet}"))
    worker = validate_worker(str(raw.get("worker") or ""))
    password = validate_password(str(raw.get("password") if raw.get("password") is not None else "x"))
    kind_raw = str(raw.get("pool_kind") or "unknown").strip().lower()
    if kind_raw not in ("solo", "shared", "unknown"):
        kind_raw = "unknown"
    # Never auto-upgrade unknown → solo
    pool_kind: PoolKind = kind_raw  # type: ignore[assignment]
    return CustomPoolConfig(
        host=host,
        port=port,
        transport=transport,
        username_format=username_format,
        worker=worker,
        password=password,
        pool_kind=pool_kind,
    )


def _selection_for(network_id: str, pool_by_network: Optional[dict]) -> dict[str, Any]:
    nid = normalize_network_id(network_id)
    raw = pool_by_network if isinstance(pool_by_network, dict) else {}
    entry = raw.get(nid)
    return entry if isinstance(entry, dict) else {}


def resolve_pool(
    network_id: str,
    pool_by_network: Optional[dict] = None,
) -> ResolvedPoolEndpoint:
    """
    Resolve connection parameters. Missing/invalid overrides fall back to default
    so existing installs keep today's endpoints.
    """
    nid = normalize_network_id(network_id)
    default = resolve_default(nid)
    sel = _selection_for(nid, pool_by_network)
    mode = str(sel.get("mode") or "default").strip().lower()
    if mode not in ("default", "preset", "custom"):
        return default
    if mode == "default":
        return default

    if mode == "preset":
        preset_id = str(sel.get("preset_id") or "").strip()
        preset = get_preset(nid, preset_id) if preset_id else None
        if preset is None:
            return default
        return ResolvedPoolEndpoint(
            network_id=nid,
            mode="preset",
            host=preset.host,
            port=int(preset.port),
            transport=preset.transport,
            username_format=preset.username_format,
            worker=str(sel.get("worker") or ""),
            password=preset.password or "x",
            pool_kind=preset.pool_kind,
            validation_profile_id=preset.validation_profile_id,
            preset_id=preset.id,
            display_name=preset.display_name,
            stats_url_template=preset.stats_url_template or "",
            notes=preset.notes or "",
        )

    # custom
    try:
        custom = _parse_custom(sel.get("custom"))
    except ValueError:
        return default
    if custom.pool_kind == "shared":
        vprof = "shared_pool"
    elif custom.pool_kind == "solo":
        vprof = "generic_solo_stratum"
    else:
        vprof = "unknown_custom"
    return ResolvedPoolEndpoint(
        network_id=nid,
        mode="custom",
        host=custom.host,
        port=custom.port,
        transport=custom.transport,
        username_format=custom.username_format,
        worker=custom.worker,
        password=custom.password,
        pool_kind=custom.pool_kind,
        validation_profile_id=vprof,
        preset_id=None,
        display_name=f"Custom ({custom.host}:{custom.port})",
        stats_url_template="",
        notes="",
    )


def reset_pool_selection(
    network_id: str,
    pool_by_network: Optional[dict] = None,
) -> dict[str, Any]:
    """Return a copy of pool_by_network with this network reset to default."""
    nid = normalize_network_id(network_id)
    out: dict[str, Any] = {}
    raw = pool_by_network if isinstance(pool_by_network, dict) else {}
    for k, v in raw.items():
        key = normalize_network_id(str(k))
        if key == nid:
            continue
        out[key] = v
    return out


def normalize_pool_by_network(raw: Any) -> dict[str, Any]:
    """Sanitize settings blob; drop garbage; never invent custom hosts."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in raw.items():
        nid = normalize_network_id(str(k))
        if not isinstance(v, dict):
            continue
        mode = str(v.get("mode") or "default").strip().lower()
        if mode not in ("default", "preset", "custom"):
            mode = "default"
        entry: dict[str, Any] = {"mode": mode}
        if mode == "preset":
            pid = str(v.get("preset_id") or "").strip()
            if pid:
                entry["preset_id"] = pid
            worker = str(v.get("worker") or "").strip()
            if worker:
                try:
                    entry["worker"] = validate_worker(worker)
                except ValueError:
                    pass
        elif mode == "custom":
            custom_raw = v.get("custom")
            if isinstance(custom_raw, dict):
                try:
                    c = _parse_custom(custom_raw)
                    entry["custom"] = {
                        "host": c.host,
                        "port": c.port,
                        "transport": c.transport,
                        "username_format": c.username_format,
                        "worker": c.worker,
                        "password": c.password,
                        "pool_kind": c.pool_kind,
                    }
                except ValueError:
                    # Invalid custom → treat as default (omit entry)
                    continue
            else:
                continue
        out[nid] = entry
    return out
