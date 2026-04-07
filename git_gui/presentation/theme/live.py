"""Live theme switching helpers.

`connect_widget` wires a widget to refresh on `ThemeManager.theme_changed`.
For widgets that built their stylesheet from f-strings (and cached the
result), pass `rebuild` so the stylesheet is rebuilt before update().

The slot is stored on the widget instance so PySide6 sees the ownership
relationship and auto-disconnects when the widget is destroyed.
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
    def _on_theme_changed(_theme: Theme) -> None:
        if rebuild is not None:
            rebuild()
        widget.update()

    # Store on the widget so the connection's lifetime is tied to it.
    widget._theme_slot = _on_theme_changed  # type: ignore[attr-defined]
    get_theme_manager().theme_changed.connect(widget._theme_slot)
