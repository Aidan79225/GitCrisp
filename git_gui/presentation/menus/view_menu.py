"""The View menu, and the diff-view choice that lives in it."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QMenu

from git_gui.presentation.app_settings import get_side_by_side_diff, set_side_by_side_diff


def view_menu(window: QMainWindow) -> QMenu:
    """The window's View menu, created on first use.

    Held on the window rather than looked up by title: two installers add to
    this menu, and matching on the label would give the second one its own
    "View" beside the first as soon as the text changed.
    """
    menu = getattr(window, "_view_menu", None)
    if menu is None:
        menu = window.menuBar().addMenu("&View")
        window._view_menu = menu  # type: ignore[attr-defined]
    return menu


def install_diff_view_menu(window: QMainWindow, on_changed: Callable[[], None]) -> None:
    """Add the `View → Side-by-side diff` toggle to *window*.

    *on_changed* is called after the preference has been written, and is what
    redraws whatever diff is on screen — a preference nothing acts on until the
    next click would look broken.
    """
    action = QAction("&Side-by-side diff", window)
    action.setCheckable(True)
    # Set the initial state before connecting: setChecked emits toggled, and a
    # redraw fired here would run against panes the window has not built yet.
    action.setChecked(get_side_by_side_diff())

    def _toggled(checked: bool) -> None:
        set_side_by_side_diff(checked)
        on_changed()

    action.toggled.connect(_toggled)
    view_menu(window).addAction(action)
    # Hold a reference to keep the action alive.
    window._side_by_side_action = action  # type: ignore[attr-defined]
