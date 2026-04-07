"""Live theme switching helpers.

`connect_widget` wires a widget to refresh on `ThemeManager.theme_changed`.
For widgets that built their stylesheet from f-strings (and cached the
result), pass `rebuild` so the stylesheet is rebuilt before update().

The connection is explicitly disconnected when the widget's C++ object is
destroyed (via the `destroyed` signal). This prevents `RuntimeError:
Internal C++ object already deleted` when the theme changes after a
widget has been removed (e.g. closing a diff and reopening another).
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtWidgets import QWidget

from .manager import get_theme_manager
from .tokens import Theme


def connect_widget(
    widget: QWidget,
    rebuild: Optional[Callable[[], None]] = None,
) -> None:
    """Refresh `widget` whenever the active theme changes.

    Args:
        widget: The widget to refresh. Its `update()` will be called.
        rebuild: Optional callable invoked before `update()` to rebuild
            cached stylesheet strings.
    """
    mgr = get_theme_manager()

    def _on_theme_changed(_theme: Theme) -> None:
        try:
            if rebuild is not None:
                rebuild()
            widget.update()
        except RuntimeError:
            # Widget C++ object was deleted between destroyed.emit and now.
            # Disconnect ourselves and swallow.
            try:
                mgr.theme_changed.disconnect(_on_theme_changed)
            except (TypeError, RuntimeError):
                pass

    mgr.theme_changed.connect(_on_theme_changed)

    def _disconnect(*_args) -> None:
        try:
            mgr.theme_changed.disconnect(_on_theme_changed)
        except (TypeError, RuntimeError):
            pass

    widget.destroyed.connect(_disconnect)
