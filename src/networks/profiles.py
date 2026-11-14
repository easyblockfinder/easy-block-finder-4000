"""Network profiles — Easy Block Finder 4000 multi-network registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class NetworkProfile:
    id: str
    display_name: str
    algorithm: str
    engine_kind: str  # native_sha256d | managed_external
    stratum_host: str
    stratum_port: int
    username_template: str  # {address} or solo:{address}
    password: str
    stats_url_template: str  # may include {address}
    hardware_hint: str
    thermal_source: str  # gpu_nvidia | cpu | none
    mining_ready: bool  # False until engine wired
    pool_fee_note: str
    engine_fee_note: str
    notes: str = ""
    coinbase_enforce_fee_split: bool = True
    coinbase_require_user_payout: bool = True
    coinbase_pool_fee_num: int = 2
    coinbase_pool_fee_den: int = 100
    explorer_status_url: str = ""
    explorer_block_url: str = ""
    explorer_kind: str = "blockstream"  # blockstream | blockchair_bch | none

    def pool_identity(self, address: str) -> str:
        """Pool worker/account id (BCH CashAddr → bitcoincash:…)."""
        addr = (address or "").strip()
        if not addr:
            return ""
        if self.id == "bch":
            lower = addr.lower()
            if lower.startswith("bitcoincash:"):
                return lower
            if ":" not in addr and lower[:1] in ("q", "p") and len(lower) >= 42:
                return f"bitcoincash:{lower}"
        return addr

    def username_for(self, address: str) -> str:
        return self.username_template.format(address=self.pool_identity(address))

    def stats_url_for(self, address: str) -> str:
        addr = self.pool_identity(address)
        if not addr or not self.stats_url_template:
            return ""
        return self.stats_url_template.format(address=addr)


PROFILES: dict[str, NetworkProfile] = {
    "btc": NetworkProfile(
        id="btc",
        display_name="Bitcoin (BTC)",
        algorithm="sha256d",
        engine_kind="native_sha256d",
        stratum_host="stratum.ckpool.org",
        stratum_port=3333,
        username_template="{address}",
        password="x",
        stats_url_template="https://raw.stats.ckpool.org/users/{address}",
        hardware_hint="GPU OpenCL (ASIC-heavy network)",
        thermal_source="gpu_nvidia",
        mining_ready=True,
        pool_fee_note="CKPool solo ~2%",
        engine_fee_note="none (native)",
        notes="Existing working path; needs regression and hardware validation.",
        coinbase_enforce_fee_split=True,
        coinbase_pool_fee_num=2,
        coinbase_pool_fee_den=100,
        explorer_status_url="https://blockstream.info/api/block/{hash}/status",
        explorer_block_url="https://blockstream.info/api/block/{hash}",
        explorer_kind="blockstream",
    ),
    "bch": NetworkProfile(
        id="bch",
        display_name="Bitcoin Cash (BCH)",
        algorithm="sha256d",
        engine_kind="native_sha256d",
        stratum_host="solo-bch.2miners.com",
        stratum_port=9393,
        username_template="{address}",
        password="x",
        stats_url_template="https://solo-bch.2miners.com/account/{address}",
        hardware_hint="GPU OpenCL (ASIC-heavy)",
        thermal_source="gpu_nvidia",
        mining_ready=True,
        pool_fee_note="2Miners SOLO (pool page)",
        engine_fee_note="none (native)",
        notes=(
            "CashAddr + native SHA-256d. 2Miners SOLO pays via pool wallet in coinbase; "
            "payout from account page (no instant on-chain script check)."
        ),
        coinbase_enforce_fee_split=False,
        coinbase_require_user_payout=False,
        coinbase_pool_fee_num=0,
        coinbase_pool_fee_den=100,
        explorer_status_url="https://api.blockchair.com/bitcoin-cash/dashboards/block/{hash}",
        explorer_block_url="https://api.blockchair.com/bitcoin-cash/dashboards/block/{hash}",
        explorer_kind="blockchair_bch",
    ),
    "xmr": NetworkProfile(
        id="xmr",
        display_name="Monero (XMR)",
        algorithm="randomx",
        engine_kind="managed_external",
        stratum_host="xmr.kryptex.network",
        stratum_port=7029,
        username_template="solo:{address}",
        password="x",
        stats_url_template="https://pool.kryptex.com/xmr/miner/stats/{address}",
        hardware_hint="CPU RandomX (XMRig 6.26.0)",
        thermal_source="cpu",
        mining_ready=True,
        pool_fee_note="Kryptex SOLO ~1%",
        engine_fee_note="XMRig donate ~1% (not added to user accepted)",
        notes=(
            "Managed XMRig; CPU temperature in UI. "
            "No automatic block/payout tracking (accepted ≠ block)."
        ),
        coinbase_enforce_fee_split=False,
        explorer_kind="none",
    ),
    "rvn": NetworkProfile(
        id="rvn",
        display_name="Ravencoin (RVN)",
        algorithm="kawpow",
        engine_kind="managed_external",
        stratum_host="solo-rvn.2miners.com",
        stratum_port=7070,
        username_template="{address}",
        password="x",
        stats_url_template="https://solo-rvn.2miners.com/account/{address}",
        hardware_hint="NVIDIA GPU (Rigel 1.23.2 KawPoW)",
        thermal_source="gpu_nvidia",
        mining_ready=True,
        pool_fee_note="2Miners SOLO",
        engine_fee_note="Rigel 1% (not added to user accepted)",
        notes=(
            "Dynamic DAG + free VRAM; GPU bus/UUID. "
            "No automatic block/payout tracking (accepted ≠ block)."
        ),
        coinbase_enforce_fee_split=False,
        explorer_kind="none",
    ),
    "erg": NetworkProfile(
        id="erg",
        display_name="Ergo (ERG)",
        algorithm="autolykos2",
        engine_kind="managed_external",
        stratum_host="solo-erg.2miners.com",
        stratum_port=9999,
        username_template="{address}",
        password="x",
        stats_url_template="https://solo-erg.2miners.com/account/{address}",
        hardware_hint="NVIDIA GPU (Rigel 1.23.2 Autolykos2)",
        thermal_source="gpu_nvidia",
        mining_ready=True,
        pool_fee_note="2Miners SOLO",
        engine_fee_note="Rigel 1% (not added to user accepted)",
        notes=(
            "Dynamic dataset + free VRAM; GPU bus/UUID. "
            "No automatic block/payout tracking (accepted ≠ block)."
        ),
        coinbase_enforce_fee_split=False,
        explorer_kind="none",
    ),
}

NETWORK_ORDER = ("btc", "bch", "xmr", "rvn", "erg")


def get_profile(network_id: str) -> NetworkProfile:
    key = (network_id or "").strip().lower()
    if key not in PROFILES:
        raise KeyError(f"Unknown network: {network_id}")
    return PROFILES[key]


def list_profiles() -> list[NetworkProfile]:
    return [PROFILES[i] for i in NETWORK_ORDER]


def normalize_network_id(network_id: Optional[str], default: str = "btc") -> str:
    key = (network_id or "").strip().lower()
    return key if key in PROFILES else default
