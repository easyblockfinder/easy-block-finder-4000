"""Official miner catalog from miners.lock.json — consent / download helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from engines.fetch_miner import load_lock, miner_install_dir


@dataclass(frozen=True)
class MinerInfo:
    id: str
    display_name: str
    version: str
    license: str
    url: str
    sha256: str
    donate_percent: float
    donate_note: str
    networks: tuple[str, ...]
    official_site: str


_DISPLAY = {
    "xmrig": ("XMRig", "https://xmrig.com"),
    "rigel": ("Rigel Miner", "https://rigelminer.com"),
}


def miner_id_for_network(network_id: str) -> Optional[str]:
    nid = (network_id or "").strip().lower()
    lock = load_lock()
    for mid, entry in lock.items():
        if not isinstance(entry, dict):
            continue
        nets = entry.get("networks") or []
        if nid in [str(x).lower() for x in nets]:
            return str(mid)
    return None


def get_miner_info(miner_id: str) -> MinerInfo:
    lock = load_lock()
    entry = lock.get(miner_id)
    if not isinstance(entry, dict):
        raise KeyError(f"Unknown miner: {miner_id}")
    name, site = _DISPLAY.get(miner_id, (miner_id, ""))
    return MinerInfo(
        id=miner_id,
        display_name=name,
        version=str(entry.get("version") or ""),
        license=str(entry.get("license") or "see upstream"),
        url=str(entry.get("url") or ""),
        sha256=str(entry.get("sha256") or ""),
        donate_percent=float(entry.get("donate_default_percent") or 0),
        donate_note=str(entry.get("donate_note") or ""),
        networks=tuple(str(x) for x in (entry.get("networks") or [])),
        official_site=site,
    )


def is_miner_installed(miner_id: str) -> bool:
    """True if a verified install for the locked version already exists."""
    lock = load_lock()
    entry = lock.get(miner_id)
    if not isinstance(entry, dict):
        return False
    version = str(entry["version"])
    expect = str(entry["sha256"]).lower()
    install_dir = miner_install_dir(miner_id, version) / f"verified_{expect[:16]}"
    marker = install_dir / ".ebf4000_verified"
    legacy = install_dir / ".soloblockstrike_verified"
    exe_name = Path(str(entry.get("exe_relpath") or "miner.exe")).name
    exe = install_dir / exe_name
    return exe.is_file() and (marker.is_file() or legacy.is_file())


def list_catalog_miner_ids() -> list[str]:
    """Stable order: xmrig, then rigel, then any other lock keys."""
    lock = load_lock()
    preferred = ("xmrig", "rigel")
    out: list[str] = []
    for mid in preferred:
        if mid in lock and isinstance(lock[mid], dict):
            out.append(mid)
    for mid, entry in lock.items():
        if mid not in out and isinstance(entry, dict):
            out.append(str(mid))
    return out


def list_missing_miners() -> list[str]:
    return [mid for mid in list_catalog_miner_ids() if not is_miner_installed(mid)]


def consent_body_for_miners(miner_ids: list[str]) -> str:
    """Human-readable consent text for the dialog."""
    lines: list[str] = [
        "EBF4000 does not bundle miner binaries. With your consent, the app may "
        "download only the engine required for your selected network from the "
        "official upstream release, then verify the SHA-256 checksum from "
        "third_party/miners.lock.json.",
        "",
        "Miners are separate programs with their own licenses and developer fees. "
        "They will not run until you press Start.",
        "",
    ]
    for mid in miner_ids:
        info = get_miner_info(mid)
        lines.append(f"— {info.display_name} {info.version}")
        lines.append(f"  License: {info.license}")
        if info.official_site:
            lines.append(f"  Website: {info.official_site}")
        lines.append(f"  Official download: {info.url}")
        lines.append(f"  SHA-256 (pinned): {info.sha256}")
        fee = info.donate_percent
        if fee:
            lines.append(f"  Developer fee (upstream): ~{fee:g}%")
        if info.donate_note:
            lines.append(f"  Note: {info.donate_note}")
        lines.append(f"  Used for: {', '.join(n.upper() for n in info.networks)}")
        lines.append("")
    lines.append(
        "Windows Defender / antivirus are not disabled or bypassed by this app."
    )
    return "\n".join(lines)


def load_consent_from_settings() -> bool:
    from ui.settings_store import load_settings

    return bool(load_settings().get("miner_download_consent", False))


def save_consent(accepted: bool) -> None:
    from ui.settings_store import save_settings

    save_settings({"miner_download_consent": bool(accepted)})
