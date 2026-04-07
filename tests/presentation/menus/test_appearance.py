"""Tests for the View → Appearance menu installer."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMainWindow

from git_gui.presentation.menus.appearance import install_appearance_menu
from git_gui.presentation.theme import get_theme_manager


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def reset_theme():
    yield
    get_theme_manager().set_mode("dark")


def _find_appearance_actions(window: QMainWindow) -> dict:
    """Return {label: QAction} from window's View → Appearance submenu."""
    bar = window.menuBar()
    view_menu = None
    for action in bar.actions():
        if action.text().replace("&", "") == "View":
            view_menu = action.menu()
            break
    assert view_menu is not None, "View menu not found"

    appearance_menu = None
    for action in view_menu.actions():
        if action.text().replace("&", "") == "Appearance":
            appearance_menu = action.menu()
            break
    assert appearance_menu is not None, "Appearance submenu not found"

    return {
        a.text().replace("&", ""): a
        for a in appearance_menu.actions()
    }


def test_install_creates_three_actions(app, reset_theme):
    window = QMainWindow()
    install_appearance_menu(window)

    actions = _find_appearance_actions(window)
    assert set(actions.keys()) == {"System", "Light", "Dark"}
    for a in actions.values():
        assert a.isCheckable()


def test_initial_check_matches_current_mode(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("dark")

    window = QMainWindow()
    install_appearance_menu(window)
    actions = _find_appearance_actions(window)

    assert actions["Dark"].isChecked()
    assert not actions["Light"].isChecked()
    assert not actions["System"].isChecked()


def test_triggering_action_changes_theme(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("dark")

    window = QMainWindow()
    install_appearance_menu(window)
    actions = _find_appearance_actions(window)

    actions["Light"].trigger()
    assert mgr.mode == "light"


def test_checkmark_updates_when_mode_changes_externally(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("dark")

    window = QMainWindow()
    install_appearance_menu(window)
    actions = _find_appearance_actions(window)

    mgr.set_mode("light")
    assert actions["Light"].isChecked()
    assert not actions["Dark"].isChecked()
