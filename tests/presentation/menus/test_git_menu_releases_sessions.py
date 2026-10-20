"""Reinstalling the Git menu lets go of the previous repository's session.

The menu is rebuilt on every repo switch, and its actions and the dialogs
they open hold that install's buses. Anything left alive keeps the old
Pygit2Repository open, which on Windows keeps its pack files locked.
"""

import gc
import weakref
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.dialogs.remote_dialog import RemoteDialog
from git_gui.presentation.menus.git_menu import install_git_menu


def _window(qtbot) -> QMainWindow:
    window = QMainWindow()
    qtbot.addWidget(window)
    return window


def _install(window: QMainWindow, session) -> None:
    install_git_menu(
        window,
        queries=session,
        commands=session,
        repo_workdir=None,
        on_open_submodule=lambda _p: None,
        on_open_worktrees_dialog=lambda: None,
        on_open_reflog=lambda: None,
        on_checkout_branch=lambda _b: None,
    )


def _collect() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()


def test_reinstalling_leaves_one_git_menu(qtbot):
    window = _window(qtbot)
    _install(window, MagicMock())
    _install(window, MagicMock())
    titles = [a.text() for a in window.menuBar().actions()]
    assert titles.count("&Git") == 1


def test_reinstalling_releases_the_previous_session(qtbot):
    window = _window(qtbot)
    old = MagicMock()
    _install(window, old)
    released = weakref.ref(old)
    del old

    _install(window, MagicMock())
    _collect()
    assert released() is None


def test_a_finished_dialog_releases_its_session(qtbot):
    window = _window(qtbot)
    old = MagicMock()
    old.list_remotes.execute.return_value = []
    _install(window, old)
    with patch.object(RemoteDialog, "exec", return_value=0):
        window._git_remote_action.trigger()
    released = weakref.ref(old)
    del old

    _install(window, MagicMock())
    _collect()
    assert released() is None
