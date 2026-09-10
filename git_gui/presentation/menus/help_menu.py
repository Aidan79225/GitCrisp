"""Install a `Help -> Preferences...` menu item that opens PreferencesDialog."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog


def install_help_menu(window: QMainWindow) -> None:
    """Add a `Help -> Preferences...` action to ``window``'s menu bar.

    Clicking the action opens the Preferences dialog (modal). The action
    is held on the window to keep it alive.
    """
    bar = window.menuBar()
    help_menu = bar.addMenu("&Help")
    action = QAction("&Preferences...", window)
    action.triggered.connect(lambda: PreferencesDialog(window).exec())
    help_menu.addAction(action)
    window._preferences_action = action  # type: ignore[attr-defined]
