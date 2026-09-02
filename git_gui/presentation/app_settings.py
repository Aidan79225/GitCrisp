"""Application-wide preferences backed by QSettings.

Keys are namespaced under group prefixes so future settings stay
organized. Add new helpers here rather than poking QSettings directly
from feature modules so tests have a single mock surface.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

_KEY_CHECK_UPDATES = "updates/check_on_startup"


def get_check_updates() -> bool:
    """Return whether the app should check for updates on startup. Default True."""
    return QSettings().value(_KEY_CHECK_UPDATES, True, type=bool)


def set_check_updates(value: bool) -> None:
    """Persist the update-check preference."""
    QSettings().setValue(_KEY_CHECK_UPDATES, value)


_KEY_WINDOW_GEOMETRY = "window/geometry"
_KEY_SPLIT = "window/split_{name}"


def get_window_geometry() -> QByteArray | None:
    """The window's saved size, position and maximized state, or None if unset.

    An opaque blob from QWidget.saveGeometry rather than a width and height:
    it carries the screen the window was on and whether it was maximized, and
    a maximized window's *restored* size along with it — none of which
    survives storing size() and pos() by hand.
    """
    value = QSettings().value(_KEY_WINDOW_GEOMETRY)
    if isinstance(value, QByteArray) and not value.isEmpty():
        return value
    return None


def set_window_geometry(value: QByteArray) -> None:
    """Persist the window's geometry blob."""
    QSettings().setValue(_KEY_WINDOW_GEOMETRY, value)


def get_split_sizes(name: str) -> list[int] | None:
    """Saved pixel sizes for one splitter, or None if it was never saved.

    Stored as text rather than as a list: QSettings' list round-trip differs
    by backend — the ini format joins with commas and hands a one-element list
    back as a bare string — so encoding it here keeps every platform reading
    what it wrote. A value that does not parse is treated as absent; a corrupt
    settings file must not stop the window opening.
    """
    raw = QSettings().value(_KEY_SPLIT.format(name=name), "", type=str)
    if not raw:
        return None
    try:
        sizes = [int(part) for part in raw.split(",")]
    except ValueError:
        return None
    if not sizes or any(size < 0 for size in sizes):
        return None
    return sizes


def set_split_sizes(name: str, sizes: list[int]) -> None:
    """Persist one splitter's pixel sizes."""
    QSettings().setValue(_KEY_SPLIT.format(name=name), ",".join(str(s) for s in sizes))
