"""Tests for the View → Appearance menu installer."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMainWindow

from git_gui.presentation.menus.appearance import install_appearance_menu


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _appearance_action(window: QMainWindow):
    bar = window.menuBar()
    for action in bar.actions():
        if action.text().replace("&", "") == "View":
            view_menu = action.menu()
            for sub in view_menu.actions():
                if sub.text().replace("&", "").rstrip(".") == "Appearance":
                    return sub
    return None


def test_install_creates_appearance_action(app):
    window = QMainWindow()
    install_appearance_menu(window)
    action = _appearance_action(window)
    assert action is not None
    # It's a single action, not a submenu.
    assert action.menu() is None


def test_triggering_action_opens_theme_dialog(app, monkeypatch):
    """The action should construct a ThemeDialog and call exec()."""
    construction_count = {"n": 0}

    def fake_exec(self):
        construction_count["n"] += 1
        return 0

    from git_gui.presentation.dialogs import theme_dialog as td
    monkeypatch.setattr(td.ThemeDialog, "exec", fake_exec)

    window = QMainWindow()
    install_appearance_menu(window)
    _appearance_action(window).trigger()
    assert construction_count["n"] == 1
