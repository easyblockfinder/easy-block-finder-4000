"""Battery / AC power status (Windows)."""

from __future__ import annotations


def on_battery() -> bool | None:
    """
    True = on battery, False = AC, None = unreadable.
    """
    try:
        import ctypes
        from ctypes import wintypes

        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", wintypes.BYTE),
                ("BatteryFlag", wintypes.BYTE),
                ("BatteryLifePercent", wintypes.BYTE),
                ("SystemStatusFlag", wintypes.BYTE),
                ("BatteryLifeTime", wintypes.DWORD),
                ("BatteryFullLifeTime", wintypes.DWORD),
            ]

        status = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return None
        ac = int(status.ACLineStatus)
        if ac == 0:
            return True
        if ac == 1:
            return False
        return None
    except Exception:
        return None
