from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.orphan_miners import (  # noqa: E402
    OrphanHit,
    kill_app_xmrig,
    list_app_xmrig,
)


def test_list_empty_when_not_windows():
    with patch("engines.orphan_miners.sys.platform", "linux"):
        assert list_app_xmrig() == []


def test_kill_filters_exclude_pid():
    hits = [
        OrphanHit(1, "xmrig.exe", "--http-access-token=ebf4000"),
        OrphanHit(2, "xmrig.exe", "--http-port=40789"),
    ]
    with (
        patch("engines.orphan_miners.list_app_xmrig", return_value=hits),
        patch("engines.orphan_miners.kill_pids", return_value=[]) as kp,
    ):
        n, failed = kill_app_xmrig(exclude_pid=1)
        assert n == 1
        assert failed == []
        kp.assert_called_once_with([2])
