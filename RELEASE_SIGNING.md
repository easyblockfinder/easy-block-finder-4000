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

## Build Windows Setup + ZIP (bundled CPython)

From a clean tree (no `.venv`, no local secrets):

1. Set `APP_VERSION` in `src/app_meta.py` to the SemVer you are releasing (e.g. `1.1.0`).
2. Build payload, ZIP, and Setup.exe (downloads embeddable Python once into `runtime\`):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_windows_release.ps1
```

Outputs:

- `dist\EBF4000-v{VERSION}-windows-setup.exe` — primary end-user installer (Python embedded)
- `dist\EBF4000-v{VERSION}-windows.zip` — portable / in-app update asset (also includes `runtime\`)

Inno Setup 6 is required for the `.exe` (the script will try `winget install JRSoftware.InnoSetup` if missing).

Sign **the ZIP** as before (in-app updater verifies `*-windows.zip` + `SHA256SUMS`). Optionally also publish the Setup.exe on the same GitHub Release for first-time installs.

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
