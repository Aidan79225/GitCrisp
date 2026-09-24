"""Install the Help menu: `Preferences...` and `About GitCrisp...`."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.dialogs.about_dialog import AboutDialog
from git_gui.presentation.dialogs.preferences_dialog import PreferencesDialog


def install_help_menu(window: QMainWindow) -> None:
    """Add the Help menu to ``window``'s menu bar.

    Each action opens its dialog (modal) and is held on the window to keep
    it alive. On macOS Qt moves both into the application menu, where users
    look for them; elsewhere they stay under Help.
    """
    bar = window.menuBar()
    help_menu = bar.addMenu("&Help")

    action = QAction("&Preferences...", window)
    action.triggered.connect(lambda: PreferencesDialog(window).exec())
    help_menu.addAction(action)
    window._preferences_action = action  # type: ignore[attr-defined]

    about = QAction("&About GitCrisp...", window)
    about.setMenuRole(QAction.MenuRole.AboutRole)
    about.triggered.connect(lambda: AboutDialog(window).exec())
    help_menu.addAction(about)
    window._about_action = about  # type: ignore[attr-defined]
