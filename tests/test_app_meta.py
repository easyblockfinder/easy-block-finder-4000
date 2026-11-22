from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from app_meta import (  # noqa: E402
    APP_DATA_DIRNAME,
    APP_NAME,
    APP_SHORT,
    APP_USER_AGENT,
    APP_VERSION,
    APP_VERSION_LABEL,
)


def test_branding_constants():
    assert APP_NAME == "Easy Block Finder 4000"
    assert APP_SHORT == "EBF4000"
    assert APP_VERSION == "1.1.0"
    assert APP_VERSION_LABEL == "EBF4000 - v1.1.0"
    assert APP_USER_AGENT == "EBF4000/1.1.0"
    assert APP_DATA_DIRNAME == "EasyBlockFinder4000"
