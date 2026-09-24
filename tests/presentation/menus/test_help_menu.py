"""Tests for the Help menu installer."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.menus.help_menu import install_help_menu


def test_about_action_opens_about_dialog(qtbot, monkeypatch):
    from git_gui.presentation.dialogs import about_dialog

    opened = []
    monkeypatch.setattr(about_dialog.AboutDialog, "exec", lambda self: opened.append(self))
    window = QMainWindow()
    qtbot.addWidget(window)
    install_help_menu(window)

    action = window._about_action
    assert action.menuRole() == QAction.MenuRole.AboutRole
    action.trigger()
    assert len(opened) == 1
