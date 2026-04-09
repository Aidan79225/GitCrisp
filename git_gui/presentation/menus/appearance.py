"""Install a `View → Appearance...` menu item that opens the Theme dialog."""
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.dialogs.theme_dialog import ThemeDialog


def install_appearance_menu(window: QMainWindow) -> None:
    """Add a `View → Appearance...` action to `window`'s menu bar.

    Clicking the action opens the Theme dialog.
    """
    bar = window.menuBar()
    view_menu = bar.addMenu("&View")
    action = QAction("&Appearance...", window)
    action.triggered.connect(lambda: ThemeDialog(window).exec())
    view_menu.addAction(action)
    # Hold a reference to keep the action alive.
    window._appearance_action = action  # type: ignore[attr-defined]
