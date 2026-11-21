from __future__ import annotations

import socket
import ssl
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from networks.pool_connection_test import probe_native_pool_connection  # noqa: E402
from stratum.client import StratumClient  # noqa: E402


def test_ssl_context_verifies_certs():
    client = StratumClient(use_tls=True)
    ctx = client._ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_tls_self_signed_fails_verification(tmp_path):
    """Generate ephemeral self-signed with openssl -config nul (Windows-safe)."""
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cfg = tmp_path / "openssl.cnf"
    cfg.write_text(
        "\n".join(
            [
                "[req]",
                "distinguished_name=req_distinguished_name",
                "x509_extensions=v3_req",
                "prompt=no",
                "[req_distinguished_name]",
                "CN=127.0.0.1",
                "[v3_req]",
                "subjectAltName=IP:127.0.0.1",
                "basicConstraints=CA:TRUE",
            ]
        ),
        encoding="ascii",
    )
    import subprocess

    proc = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-nodes",
            "-config",
            str(cfg),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # Still assert production path never disables verify even if openssl missing.
        client = StratumClient(use_tls=True)
        assert client._ssl_context().verify_mode == ssl.CERT_REQUIRED
        return

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert_path), str(key_path))
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    stop = threading.Event()

    def _serve() -> None:
        server.settimeout(0.5)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                tls = ctx.wrap_socket(conn, server_side=True)
                tls.settimeout(1)
                try:
                    tls.recv(64)
                except OSError:
                    pass
                tls.close()
            except Exception:
                try:
                    conn.close()
                except OSError:
                    pass

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    try:
        result = probe_native_pool_connection(
            host="127.0.0.1",
            port=port,
            username="bc1qtest",
            transport="tls",
            timeout_s=4.0,
        )
        assert result.ok is False
        msg = result.message.lower()
        assert any(
            k in msg
            for k in (
                "certificate",
                "tls",
                "ssl",
                "handshake",
                "connect",
                "verification",
                "failed",
            )
        )
    finally:
        stop.set()
        try:
            server.close()
        except OSError:
            pass
        t.join(timeout=2)
