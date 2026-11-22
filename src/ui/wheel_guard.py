"""Never change spin/combo values with the mouse wheel.

Wheel over a QSpinBox/QComboBox (or their inner QLineEdit) must scroll the
page — not quietly nudge intensity / temperature / pool port. Values change
via click arrows, dropdown, or keyboard only.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QWidget,
)


def _host_spin_or_combo(obj: QObject) -> QWidget | None:
    cur: QObject | None = obj
    while cur is not None:
        if isinstance(cur, (QAbstractSpinBox, QComboBox)):
            return cur  # type: ignore[return-value]
        cur = cur.parent()
    return None


def harden_wheel_widgets(root: QWidget | None) -> None:
    """StrongFocus + per-widget filter on all spin/combo under root."""
    global _filter
    if root is None or _filter is None:
        return
    widgets: list[QWidget] = []
    if isinstance(root, (QAbstractSpinBox, QComboBox)):
        widgets.append(root)
    widgets.extend(root.findChildren(QAbstractSpinBox))
    widgets.extend(root.findChildren(QComboBox))
    seen: set[int] = set()
    for w in widgets:
        wid = id(w)
        if wid in seen:
            continue
        seen.add(wid)
        w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        w.installEventFilter(_filter)
        for child in w.findChildren(QWidget):
            cid = id(child)
            if cid in seen:
                continue
            seen.add(cid)
            child.installEventFilter(_filter)


class _WheelGuardFilter(QObject):
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Wheel:
            return False
        host = _host_spin_or_combo(obj)
        if host is None:
            return False
        # Always block wheel → value change; scroll nearest scroll area instead.
        parent = host.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                QApplication.sendEvent(parent.viewport(), event)
                return True
            parent = parent.parentWidget()
        return True


_filter: _WheelGuardFilter | None = None


def install_wheel_guard(app: QApplication) -> None:
    """Install once on the QApplication (covers dialogs + main window)."""
    global _filter
    if _filter is not None:
        return
    _filter = _WheelGuardFilter(app)
    app.installEventFilter(_filter)
