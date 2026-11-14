"""Unit tests for SemVer, checksums, zip safety, minisign, policy."""

from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path

import pytest

from update.checksums import parse_sha256sums, sha256_file, verify_file_digest
from update.minisign_verify import MinisignError, verify_data
from update.policy import PolicyError, assert_manifest_identity, assert_upgrade_allowed
from update.semver import parse_version, version_gt
from update.zip_safe import UnsafeZipError, safe_extract


def test_semver_compare() -> None:
    assert version_gt("1.1.0", "1.0.0")
    assert version_gt("1.0.1", "1.0.0")
    assert version_gt("2.0.0", "1.9.9")
    assert not version_gt("1.0.0", "1.0.0")
    assert not version_gt("1.0.0", "1.1.0")
    assert parse_version("v1.2.3").patch == 3


def test_upgrade_policy_blocks_downgrade() -> None:
    assert_upgrade_allowed("1.0.0", "v1.1.0")
    with pytest.raises(PolicyError):
        assert_upgrade_allowed("1.1.0", "v1.0.0")
    with pytest.raises(PolicyError):
        assert_upgrade_allowed("1.1.0", "v1.1.0")


def test_manifest_identity() -> None:
    from update.semver import parse_version

    v = parse_version("1.1.0")
    assert_manifest_identity(
        trusted_comment="timestamp:1 file:SHA256SUMS version:1.1.0 asset:EBF4000-v1.1.0-windows.zip",
        remote_version=v,
        zip_name="EBF4000-v1.1.0-windows.zip",
    )
    with pytest.raises(PolicyError):
        assert_manifest_identity(
            trusted_comment="version:9.9.9",
            remote_version=v,
            zip_name="EBF4000-v1.1.0-windows.zip",
        )


def test_sha256sums_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "EBF4000-v1.1.0-windows.zip"
    f.write_bytes(b"hello-update")
    digest = sha256_file(f)
    text = f"{digest}  {f.name}\n"
    parsed = parse_sha256sums(text)
    assert parsed[f.name] == digest
    verify_file_digest(f, digest)


def test_safe_zip_blocks_traversal(tmp_path: Path) -> None:
    zpath = tmp_path / "bad.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(UnsafeZipError):
        safe_extract(zpath, tmp_path / "out")


def test_safe_zip_ok(tmp_path: Path) -> None:
    zpath = tmp_path / "ok.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("EBF4000-v1.1.0/start.bat", "@echo off\n")
        zf.writestr("EBF4000-v1.1.0/src/main.py", "print(1)\n")
    root = safe_extract(zpath, tmp_path / "out")
    assert (root / "start.bat").is_file()


def _sign(data: bytes, seed: bytes, key_id: bytes, trusted: str) -> tuple[str, str]:
    from nacl.signing import SigningKey

    sk = SigningKey(seed)
    vk = sk.verify_key
    pub_b64 = base64.b64encode(b"Ed" + key_id + vk.encode()).decode("ascii")
    digest = hashlib.blake2b(data, digest_size=64).digest()
    file_sig = sk.sign(digest).signature
    packet = b"ED" + key_id + file_sig
    global_sig = sk.sign(packet + trusted.encode("utf-8")).signature
    sig_text = "\n".join(
        [
            "untrusted comment: test",
            base64.b64encode(packet).decode("ascii"),
            f"trusted comment: {trusted}",
            base64.b64encode(global_sig).decode("ascii"),
            "",
        ]
    )
    return pub_b64, sig_text


def test_minisign_verify_roundtrip() -> None:
    from nacl.signing import SigningKey

    seed = SigningKey.generate().encode()
    key_id = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    data = b"abc123SUMS\n"
    trusted = "timestamp:1 version:1.1.0 asset:EBF4000-v1.1.0-windows.zip"
    pub, sig = _sign(data, seed, key_id, trusted)
    out = verify_data(data, sig, public_keys_b64=(pub,))
    assert "version:1.1.0" in out


def test_minisign_rejects_tamper() -> None:
    from nacl.signing import SigningKey

    seed = SigningKey.generate().encode()
    key_id = b"\x11" * 8
    data = b"good"
    pub, sig = _sign(data, seed, key_id, "version:1.0.0")
    with pytest.raises(MinisignError):
        verify_data(b"tampered", sig, public_keys_b64=(pub,))
