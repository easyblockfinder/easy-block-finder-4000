"""Per-pool validation profiles — never a global coinbase kill switch."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationProfile:
    id: str
    enforce_fee_split: bool
    require_user_payout: bool
    fee_num: int = 0
    fee_den: int = 100
    # UI: show that payout cannot be verified from coinbase
    payout_unverified_banner: bool = False
    banner_text: str = ""


_PROFILES: dict[str, ValidationProfile] = {
    "ckpool_btc_solo": ValidationProfile(
        id="ckpool_btc_solo",
        enforce_fee_split=True,
        require_user_payout=True,
        fee_num=2,
        fee_den=100,
    ),
    "bch_pool_wallet": ValidationProfile(
        id="bch_pool_wallet",
        enforce_fee_split=False,
        require_user_payout=False,
        payout_unverified_banner=True,
        banner_text=(
            "Payout is via the pool account wallet — coinbase does not guarantee "
            "an on-chain payment to your address."
        ),
    ),
    "generic_solo_stratum": ValidationProfile(
        id="generic_solo_stratum",
        enforce_fee_split=False,
        require_user_payout=False,
        payout_unverified_banner=True,
        banner_text=(
            "Solo pool — payout layout could not be fully verified. "
            "Confirm rewards on the pool’s account page."
        ),
    ),
    "shared_pool": ValidationProfile(
        id="shared_pool",
        enforce_fee_split=False,
        require_user_payout=False,
        payout_unverified_banner=True,
        banner_text=(
            "SHARED pool — this is not solo block mining. "
            "Do not expect a full block reward from this connection."
        ),
    ),
    "unknown_custom": ValidationProfile(
        id="unknown_custom",
        enforce_fee_split=False,
        require_user_payout=False,
        payout_unverified_banner=True,
        banner_text=(
            "UNKNOWN pool — payout to your wallet could not be verified. "
            "Proceed only if you trust this pool."
        ),
    ),
    # External engines: coinbase N/A; banner still useful for shared/unknown.
    "external_default": ValidationProfile(
        id="external_default",
        enforce_fee_split=False,
        require_user_payout=False,
        payout_unverified_banner=False,
    ),
}


def get_validation_profile(profile_id: str) -> ValidationProfile:
    key = (profile_id or "").strip()
    if key not in _PROFILES:
        return _PROFILES["unknown_custom"]
    return _PROFILES[key]


def default_validation_profile_id(network_id: str) -> str:
    nid = (network_id or "").strip().lower()
    if nid == "btc":
        return "ckpool_btc_solo"
    if nid == "bch":
        return "bch_pool_wallet"
    if nid in ("xmr", "rvn", "erg"):
        return "external_default"
    return "unknown_custom"
