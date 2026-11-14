"""
Minisign signature verification (verify-only).

Compatible with official `minisign` (jedisct1) default ED (BLAKE2b-512) signatures.
Uses PyNaCl for Ed25519. Does not implement signing in the app runtime.
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from update.trusted_keys import PINNED_MINISIGN_PUBLIC_KEYS


class MinisignError(Exception):
    """Signature or key parse/verify failure (fail closed)."""


_COMMENT_UNTRUSTED = re.compile(r"^untrusted comment:\s*(.*)$", re.I)
_COMMENT_TRUSTED = re.compile(r"^trusted comment:\s*(.*)$", re.I)


def _b64decode(line: str) -> bytes:
    try:
        return base64.b64decode(line.strip(), validate=False)
    except Exception as exc:
        raise MinisignError(f"Invalid base64 in minisign data: {exc}") from exc


def parse_public_key_b64(public_key_b64: str) -> tuple[bytes, VerifyKey]:
    raw = _b64decode(public_key_b64)
    if len(raw) < 42:
        raise MinisignError("Public key too short")
    if raw[0:2] != b"Ed":
        raise MinisignError(f"Unsupported public key algorithm: {raw[0:2]!r}")
    key_id = raw[2:10]
    return key_id, VerifyKey(raw[10:42])


def parse_signature_file(text: str) -> tuple[bytes, bytes, str, bytes]:
    """
    Returns (sig_packet_74, key_id, trusted_comment, global_sig).
    sig_packet = alg[2] || key_id[8] || sig[64]
    """
    lines = [ln.rstrip("\r") for ln in text.splitlines() if ln.strip() != ""]
    if len(lines) < 4:
        raise MinisignError("Signature file incomplete (need 4 lines)")
    if not _COMMENT_UNTRUSTED.match(lines[0]):
        raise MinisignError("Missing untrusted comment line")
    sig_packet = _b64decode(lines[1])
    if len(sig_packet) != 74:
        raise MinisignError(f"Signature packet length {len(sig_packet)} != 74")
    m = _COMMENT_TRUSTED.match(lines[2])
    if not m:
        raise MinisignError("Missing trusted comment line")
    trusted = m.group(1)
    global_sig = _b64decode(lines[3])
    if len(global_sig) != 64:
        raise MinisignError("Global signature must be 64 bytes")
    key_id = sig_packet[2:10]
    return sig_packet, key_id, trusted, global_sig


def _message_for_alg(sig_alg: bytes, data: bytes) -> bytes:
    if sig_alg == b"ED":
        return hashlib.blake2b(data, digest_size=64).digest()
    if sig_alg == b"Ed":
        return data
    raise MinisignError(f"Unsupported signature algorithm: {sig_alg!r}")


def verify_data(
    data: bytes,
    signature_text: str,
    *,
    public_keys_b64: tuple[str, ...] | list[str] | None = None,
) -> str:
    """
    Verify minisign signature over `data`.
    Returns the trusted comment string on success.
    Raises MinisignError on any failure.
    """
    keys = tuple(public_keys_b64 or PINNED_MINISIGN_PUBLIC_KEYS)
    if not keys:
        raise MinisignError("No pinned public keys configured")

    sig_packet, key_id, trusted, global_sig = parse_signature_file(signature_text)
    sig_alg = sig_packet[0:2]
    file_sig = sig_packet[10:74]
    msg = _message_for_alg(sig_alg, data)

    last_err: Exception | None = None
    for pk_b64 in keys:
        try:
            pk_id, vk = parse_public_key_b64(pk_b64)
            if pk_id != key_id:
                # Allow verify anyway if key bytes match a pinned key — key_id must match
                last_err = MinisignError("minisign key id mismatch for pinned key")
                continue
            try:
                vk.verify(sig_packet + trusted.encode("utf-8"), global_sig)
            except BadSignatureError as exc:
                raise MinisignError("Global signature invalid") from exc
            try:
                vk.verify(msg, file_sig)
            except BadSignatureError as exc:
                raise MinisignError("File signature invalid") from exc
            return trusted
        except MinisignError as exc:
            last_err = exc
            continue
    raise MinisignError(str(last_err) if last_err else "No matching pinned public key")


def verify_file(
    path: Path,
    sig_path: Path,
    *,
    public_keys_b64: tuple[str, ...] | list[str] | None = None,
) -> str:
    data = path.read_bytes()
    sig_text = sig_path.read_text(encoding="utf-8")
    return verify_data(data, sig_text, public_keys_b64=public_keys_b64)
