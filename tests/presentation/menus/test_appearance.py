"""Tests for the View → Appearance menu installer."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow

from git_gui.presentation.dialogs.theme_dialog import ThemeDialog
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


def _cancel_the_dialog_that_is_up(opened: list[str]) -> None:
    dialog = QApplication.activeModalWidget()
    if dialog is not None:
        opened.append(type(dialog).__name__)
        dialog.reject()


def _open_appearance_and_cancel(window: QMainWindow) -> list[str]:
    """Choose View > Appearance, and cancel the dialog from inside its exec().

    The exec() is the real one: a stub skips what PySide does to a dialog it
    runs, and every dialog then looks as if it had been leaked.
    """
    opened: list[str] = []
    QTimer.singleShot(0, lambda: _cancel_the_dialog_that_is_up(opened))
    _appearance_action(window).trigger()
    # What the event loop does at its next turn.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return opened


def test_each_opening_of_the_dialog_is_freed_once_it_is_closed(qtbot):
    """A ThemeDialog connects closures that capture it to its own widgets, so
    one nobody deletes stays a child of the window with its 150 or so widgets,
    and every later theme change restyles it."""
    window = QMainWindow()
    qtbot.addWidget(window)
    install_appearance_menu(window)

    for opening in (1, 2):
        opened = _open_appearance_and_cancel(window)

        assert opened == ["ThemeDialog"]
        left = len(window.findChildren(ThemeDialog))
        assert left == 0, f"{left} Theme dialog(s) still under the window after opening {opening}"
