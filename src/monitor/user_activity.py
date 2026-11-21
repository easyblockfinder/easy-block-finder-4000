"""Windows user idle time via GetLastInputInfo — never records key contents."""

from __future__ import annotations

import sys
import time
from typing import Optional


def idle_seconds() -> Optional[float]:
    """
    Seconds since last keyboard/mouse input.
    Returns None on failure (caller must treat as ACTIVE / not idle).
    Does not read or store any key or pointer payload — only a tick count.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwTime", wintypes.DWORD),
            ]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick = int(kernel32.GetTickCount())
        last = int(info.dwTime)
        # GetTickCount wraps ~49.7 days; unsigned 32-bit delta.
        idle_ms = (tick - last) & 0xFFFFFFFF
        return float(idle_ms) / 1000.0
    except Exception:
        return None


def monotonic_now() -> float:
    return time.monotonic()
