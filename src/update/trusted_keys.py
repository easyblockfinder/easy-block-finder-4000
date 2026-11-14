"""
Pinned minisign public key(s) for release verification.

Trust anchor ships with the installed app. Network-fetched code cannot replace this.
Private keys are NEVER stored in this repository.

Key rotation: only via a new install from a trusted channel (or a future
signed rotation document verified by the previous key). Downgrades are rejected.
"""

from __future__ import annotations

# Base64 public key line (minisign-compatible). See RELEASE_SIGNING.md.
# Tests may pass public_keys_b64=... to bypass this pin.
PINNED_MINISIGN_PUBLIC_KEYS: tuple[str, ...] = (
    "RWRqrPTtx0vHZ/cW8O1CnL80fQW6zbAwl3F5zSeMlrbPeDQMv+xeHSac",
)

# Asset name pattern for the Windows ZIP channel (EXE/installer later).
ZIP_ASSET_PREFIX = "EBF4000-v"
ZIP_ASSET_SUFFIX = "-windows.zip"
MANIFEST_NAME = "SHA256SUMS"
MANIFEST_SIG_NAME = "SHA256SUMS.minisig"

GITHUB_OWNER = "easyblockfinder"
GITHUB_REPO = "easy-block-finder-4000"
GITHUB_API_LATEST = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
