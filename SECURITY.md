# Security Policy

## Easy Block Finder 4000

We take software security and user transparency seriously.

### Official Downloads

Download Easy Block Finder 4000 only from the official GitHub repository:

https://github.com/easyblockfinder/easy-block-finder-4000

Official releases are published through GitHub Releases.

### Application auto-update

Stable updates are offered from GitHub Releases (`EBF4000-v*-windows.zip` + `SHA256SUMS` + `SHA256SUMS.minisig`).

- Checks run in the background (default every 24 hours) or via **Help → Check for Updates…**.
- Installation requires explicit **Update Now** confirmation.
- The app verifies the minisign signature with a **pinned public key** shipped in the install (`src/update/trusted_keys.py`), then checks the ZIP SHA-256 from the signed manifest. A GitHub checksum alone is not treated as publisher authentication.
- Files are applied by an external updater after the UI exits; AppData settings, wallets, logs, and consented miners are preserved.
- Failed updates restore the previous install tree. Windows Defender is never disabled.

Maintainer signing steps: [RELEASE_SIGNING.md](RELEASE_SIGNING.md).

### Antivirus and Windows Defender

Cryptocurrency mining software may trigger security warnings due to its behavior or third-party mining engines.

Not every antivirus detection is a false positive.

Users should not disable antivirus protection or bypass security warnings without understanding the risks.

### Mining Permissions

EBF4000 must only be used on devices owned by the user or operated with explicit authorization.

Mining activity should remain under the user's control.

### Reporting Vulnerabilities

If you discover a potential security vulnerability, please use GitHub's private vulnerability reporting feature when available.

Avoid publicly disclosing exploitable vulnerabilities before the maintainer has had an opportunity to review them.

### External Miner Downloads

Third-party mining engines are not included in the official EBF4000 application package.

When XMR / RVN / ERG requires an engine, EBF4000 asks for explicit consent, then downloads only that engine from the pinned official GitHub release and verifies SHA-256 (`third_party/miners.lock.json`). Engines do not start until the user presses Start.

Users should review publisher terms, licenses, developer fees, and antivirus warnings. Security warnings must not automatically be treated as false positives.

EBF4000 must not bypass Windows security protections or download third-party miners without informed user consent.

### Third-Party Components

EBF4000 may use independently developed mining software, including XMRig and Rigel.

These components are governed by their respective licenses and security policies.

See [Third-Party Notices](THIRD_PARTY_NOTICES.md) for additional information.
