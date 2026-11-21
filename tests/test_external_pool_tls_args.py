from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.rigel_runner import RigelRunner  # noqa: E402
from engines.xmrig_runner import XmrigRunner  # noqa: E402


def test_xmrig_adds_tls_flag():
    runner = XmrigRunner(
        Path("xmrig.exe"),
        host="xmr.example.com",
        port=8029,
        username="solo:wallet",
        use_tls=True,
    )
    with patch("engines.orphan_miners.kill_app_xmrig", return_value=(0, [])):
        with patch("engines.xmrig_runner.subprocess.Popen") as popen:
            popen.return_value = MagicMock(
                poll=MagicMock(return_value=None), stdout=None
            )
            runner.start()
            cmd = popen.call_args.args[0]
            assert "--tls" in cmd
            assert "--url=xmr.example.com:8029" in cmd


def test_rigel_uses_ssl_scheme():
    runner = RigelRunner(
        Path("rigel.exe"),
        algorithm="kawpow",
        coin="rvn",
        host="solo-rvn.example.com",
        port=17070,
        username="wallet",
        use_tls=True,
    )
    with patch("engines.rigel_runner.subprocess.Popen") as popen:
        popen.return_value = MagicMock(poll=MagicMock(return_value=None), stdout=None)
        runner.start()
        cmd = popen.call_args.args[0]
        assert "stratum+ssl://solo-rvn.example.com:17070" in cmd


def test_rigel_tcp_scheme_default():
    runner = RigelRunner(
        Path("rigel.exe"),
        algorithm="autolykos2",
        coin="erg",
        host="solo-erg.example.com",
        port=9999,
        username="wallet",
        use_tls=False,
    )
    with patch("engines.rigel_runner.subprocess.Popen") as popen:
        popen.return_value = MagicMock(poll=MagicMock(return_value=None), stdout=None)
        runner.start()
        cmd = popen.call_args.args[0]
        assert "stratum+tcp://solo-erg.example.com:9999" in cmd
