"""Install a `View → Appearance` submenu for switching the app theme."""
from __future__ import annotations

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.theme import get_theme_manager


_MODE_LABELS: list[tuple[str, str]] = [
    ("system", "System"),
    ("light",  "Light"),
    ("dark",   "Dark"),
]


def install_appearance_menu(window: QMainWindow) -> None:
    """Add a `View → Appearance` submenu to `window`'s menu bar.

    Creates the View menu on the window's QMenuBar. Each of the three
    mode actions (System / Light / Dark) is checkable and exclusive; the
    currently-active mode is checked on construction and re-checked when
    ThemeManager.theme_changed fires.
    """
    bar = window.menuBar()
    view_menu = bar.addMenu("&View")
    appearance = view_menu.addMenu("&Appearance")

    group = QActionGroup(window)
    group.setExclusive(True)

    mgr = get_theme_manager()
    actions: dict[str, QAction] = {}
    for mode, label in _MODE_LABELS:
        action = QAction(label, window)
        action.setCheckable(True)
        action.setChecked(mgr.mode == mode)
        action.triggered.connect(
            lambda _checked=False, m=mode: mgr.set_mode(m)
        )
        group.addAction(action)
        appearance.addAction(action)
        actions[mode] = action

    def _on_theme_changed(_theme) -> None:
        current = mgr.mode
        if current in actions:
            actions[current].setChecked(True)

    mgr.theme_changed.connect(_on_theme_changed)

    def _disconnect() -> None:
        try:
            mgr.theme_changed.disconnect(_on_theme_changed)
        except (RuntimeError, TypeError):
            pass

    window.destroyed.connect(lambda _=None: _disconnect())

    # Hold a reference so neither the actions dict nor the slot is GC'd.
    window._appearance_actions = actions  # type: ignore[attr-defined]
    window._appearance_on_theme_changed = _on_theme_changed  # type: ignore[attr-defined]
