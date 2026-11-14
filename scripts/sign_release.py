"""
Build SHA256SUMS + SHA256SUMS.minisig for a release folder.

Private key path (default): %USERPROFILE%\\.ebf4000-release-keys\\ebf4000.minisign.key.json

  py -3 scripts/sign_release.py --dir dist/EBF4000-v1.1.0 --version 1.1.0
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sign_minisign(data: bytes, key_doc: dict, trusted_comment: str) -> str:
    from nacl.signing import SigningKey

    key_id = base64.b64decode(key_doc["key_id_b64"])
    seed = base64.b64decode(key_doc["seed_b64"])
    sk = SigningKey(seed)
    # ED = sign BLAKE2b-512(data)
    digest = hashlib.blake2b(data, digest_size=64).digest()
    file_sig = sk.sign(digest).signature  # 64 bytes
    sig_alg = b"ED"
    sig_packet = sig_alg + key_id + file_sig
    global_sig = sk.sign(sig_packet + trusted_comment.encode("utf-8")).signature
    lines = [
        "untrusted comment: signature from EBF4000 release key",
        base64.b64encode(sig_packet).decode("ascii"),
        f"trusted comment: {trusted_comment}",
        base64.b64encode(global_sig).decode("ascii"),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    try:
        import nacl  # noqa: F401
    except ImportError:
        print("Install PyNaCl: pip install PyNaCl", file=sys.stderr)
        return 2

    default_key = (
        Path(os.environ.get("USERPROFILE") or Path.home())
        / ".ebf4000-release-keys"
        / "ebf4000.minisign.key.json"
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, required=True, help="Folder containing the ZIP")
    ap.add_argument("--version", required=True, help="SemVer e.g. 1.1.0")
    ap.add_argument("--key", type=Path, default=default_key)
    ap.add_argument(
        "--zip-name",
        default="",
        help="Override zip filename (default EBF4000-v{version}-windows.zip)",
    )
    args = ap.parse_args()

    if not args.key.is_file():
        print(f"Secret key not found: {args.key}", file=sys.stderr)
        print("Run: py -3 scripts/gen_update_keypair.py", file=sys.stderr)
        return 2

    key_doc = json.loads(args.key.read_text(encoding="utf-8"))
    zip_name = args.zip_name or f"EBF4000-v{args.version}-windows.zip"
    zip_path = args.dir / zip_name
    if not zip_path.is_file():
        # accept any single matching zip in dir
        matches = list(args.dir.glob("EBF4000-v*-windows.zip"))
        if len(matches) == 1:
            zip_path = matches[0]
            zip_name = zip_path.name
        else:
            print(f"ZIP not found: {zip_path}", file=sys.stderr)
            return 2

    digest = sha256_file(zip_path)
    sums_bytes = f"{digest}  {zip_name}\n".encode("utf-8")
    sums_path = args.dir / "SHA256SUMS"
    # Exact LF bytes — Windows text mode would alter the signed payload
    sums_path.write_bytes(sums_bytes)

    trusted = (
        f"timestamp:{int(time.time())} "
        f"file:SHA256SUMS version:{args.version} asset:{zip_name}"
    )
    sig_text = sign_minisign(sums_bytes, key_doc, trusted)
    sig_path = args.dir / "SHA256SUMS.minisig"
    sig_path.write_bytes(sig_text.encode("utf-8"))

    # Self-check with app verifier (bytes on disk must match)
    from update.minisign_verify import verify_file
    from update.trusted_keys import PINNED_MINISIGN_PUBLIC_KEYS

    pub = key_doc.get("public_b64") or PINNED_MINISIGN_PUBLIC_KEYS[0]
    verify_file(sums_path, sig_path, public_keys_b64=(pub,))
    print(f"Wrote {sums_path}")
    print(f"Wrote {sig_path}")
    print("Signature self-check OK")
    print("Upload ZIP + SHA256SUMS + SHA256SUMS.minisig to the GitHub Release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
