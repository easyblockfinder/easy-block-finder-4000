"""
Generate a minisign-compatible keypair for EBF4000 releases.

Private key is written OUTSIDE the repo by default.
Public key line is printed for src/update/trusted_keys.py.

  py -3 scripts/gen_update_keypair.py --out-dir %USERPROFILE%\\.ebf4000-release-keys
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    try:
        from nacl.signing import SigningKey
    except ImportError:
        print("Install PyNaCl first: pip install PyNaCl", file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser()
    default_out = Path(os.environ.get("USERPROFILE") or Path.home()) / ".ebf4000-release-keys"
    ap.add_argument("--out-dir", type=Path, default=default_out)
    ap.add_argument(
        "--write-trusted-keys",
        action="store_true",
        help="Overwrite PINNED key in src/update/trusted_keys.py (public only)",
    )
    args = ap.parse_args()
    out: Path = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    sk = SigningKey.generate()
    vk = sk.verify_key
    key_id = secrets.token_bytes(8)
    pub_blob = b"Ed" + key_id + vk.encode()
    pub_b64 = base64.b64encode(pub_blob).decode("ascii")

    # Store raw seed + key_id for our sign_release.py (not encrypted — protect the folder)
    secret_path = out / "ebf4000.minisign.key.json"
    import json

    secret_path.write_text(
        json.dumps(
            {
                "format": "ebf4000-minisign-v1",
                "key_id_b64": base64.b64encode(key_id).decode("ascii"),
                "seed_b64": base64.b64encode(sk.encode()).decode("ascii"),
                "public_b64": pub_b64,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    try:
        os.chmod(secret_path, 0o600)
    except OSError:
        pass

    pub_path = out / "ebf4000.minisign.pub"
    pub_path.write_text(
        "untrusted comment: EBF4000 release public key\n" + pub_b64 + "\n",
        encoding="utf-8",
    )

    print("Public key (pin this):")
    print(pub_b64)
    print(f"Secret key file: {secret_path}")
    print("Keep the secret key offline / encrypted backup. NEVER commit it.")

    if args.write_trusted_keys:
        tk = SRC / "update" / "trusted_keys.py"
        text = tk.read_text(encoding="utf-8")
        import re

        new_text, n = re.subn(
            r'PINNED_MINISIGN_PUBLIC_KEYS: tuple\[str, \.\.\.\] = \(\s*#[^\n]*\n\s*#[^\n]*\n\s*"[^"]*"\s*,\s*\)',
            "PINNED_MINISIGN_PUBLIC_KEYS: tuple[str, ...] = (\n"
            "    # EBF4000 release signing public key (minisign-compatible).\n"
            f'    "{pub_b64}",\n'
            ")",
            text,
            count=1,
        )
        if n != 1:
            # simpler replace of the placeholder string
            new_text = text.replace(
                "RWQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                pub_b64,
            )
        tk.write_text(new_text, encoding="utf-8")
        print(f"Updated {tk}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
