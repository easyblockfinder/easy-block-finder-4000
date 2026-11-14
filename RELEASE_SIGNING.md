# EBF4000 release signing & auto-update publishing

Private keys never go in git, GitHub, or the ZIP. Only the **public** minisign key is pinned in `src/update/trusted_keys.py`.

## One-time key generation (maintainer machine)

```bat
py -3 -m pip install PyNaCl
py -3 scripts\gen_update_keypair.py --write-trusted-keys
```

Secret key default path:

`%USERPROFILE%\.ebf4000-release-keys\ebf4000.minisign.key.json`

Back up that folder offline. Commit only the updated public key in `trusted_keys.py`.

## Build a Windows ZIP (channel C — source tree)

From a clean tree (no `.venv`, no local secrets):

1. Set `APP_VERSION` in `src/app_meta.py` to the SemVer you are releasing (e.g. `1.1.0`).
2. Pack:

```bat
mkdir dist
powershell -Command "Compress-Archive -Path start.bat,src,scripts,requirements.txt,third_party,assets,LICENSE,README.md,SECURITY.md,THIRD_PARTY_NOTICES.md,DONATE.md,TRADEMARKS.md,RELEASE_SIGNING.md -DestinationPath dist\EBF4000-v1.1.0-windows.zip"
```

Use the exact name: `EBF4000-v{VERSION}-windows.zip`.

## Sign the package

```bat
py -3 scripts\sign_release.py --dir dist --version 1.1.0
```

Produces next to the ZIP:

- `SHA256SUMS`
- `SHA256SUMS.minisig`

Trusted comment includes `version:` and `asset:` — the updater rejects mismatches / downgrades.

## Publish on GitHub Releases

1. Tag `v1.1.0` (or matching SemVer).
2. Create a **stable** (non-prerelease) Release on  
   `easyblockfinder/easy-block-finder-4000`.
3. Upload **all three** files:
   - `EBF4000-v1.1.0-windows.zip`
   - `SHA256SUMS`
   - `SHA256SUMS.minisig`
4. Do **not** put miner binaries or the private key in the Release.

Future EXE/installer assets may be added under the same tag with their own lines in `SHA256SUMS` (ZIP channel remains the default for the Python/`start.bat` updater).

## Client behavior (installed app)

- Background check every 24h (`Help → Check for Updates…` forces a check).
- User must click **Update Now**.
- Download → minisign verify `SHA256SUMS` → SHA-256 of ZIP → safe extract → stop mining → `scripts/apply_update.py` replaces install files → restart `start.bat`.
- `%LOCALAPPDATA%\EasyBlockFinder4000` (settings, wallets, miners, logs) is not overwritten.
- Failure leaves the previous install (backup under `updates\backup-*`).
- Defender / AV is never disabled.

## Key rotation

Rotation requires a **trusted** new install (or a future signed rotation document verified by the previous key). Network-fetched code cannot change `PINNED_MINISIGN_PUBLIC_KEYS`.
