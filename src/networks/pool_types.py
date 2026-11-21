"""Pool selection types — default / preset / custom endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

PoolMode = Literal["default", "preset", "custom"]
PoolKind = Literal["solo", "shared", "unknown"]
Transport = Literal["tcp", "tls"]


@dataclass(frozen=True)
class CustomPoolConfig:
    host: str
    port: int
    transport: Transport = "tcp"
    username_format: str = "{wallet}"
    worker: str = ""
    password: str = "x"
    pool_kind: PoolKind = "unknown"


@dataclass(frozen=True)
class ResolvedPoolEndpoint:
    """Concrete connection parameters for one mining start."""

    network_id: str
    mode: PoolMode
    host: str
    port: int
    transport: Transport
    username_format: str
    worker: str
    password: str
    pool_kind: PoolKind
    validation_profile_id: str
    preset_id: Optional[str] = None
    display_name: str = ""
    stats_url_template: str = ""
    notes: str = ""

    def render_username(self, wallet: str) -> str:
        w = (wallet or "").strip()
        worker = (self.worker or "").strip()
        fmt = self.username_format or "{wallet}"
        # Support both {wallet} and legacy {address} placeholder.
        try:
            return fmt.format(wallet=w, address=w, worker=worker)
        except (KeyError, ValueError, IndexError):
            return w


@dataclass(frozen=True)
class PoolPreset:
    id: str
    network_id: str
    display_name: str
    host: str
    port: int
    transport: Transport
    username_format: str
    password: str
    pool_kind: PoolKind
    validation_profile_id: str
    stats_url_template: str = ""
    notes: str = ""
