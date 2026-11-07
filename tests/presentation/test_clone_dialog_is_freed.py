"""A Clone dialog the window has finished with is deleted, not kept as a hidden child.

The window parents every Clone dialog to itself and ran it with exec(), and
nothing deleted it: each cancelled, failed or finished clone left a hidden
dialog behind, with the listener that restyles it on every theme switch, until
the window closed.

A cancelled clone is the exception to deleting at once. Its worker is still
removing what git wrote and reports what it could not remove through the
dialog, so the dialog goes only when that worker has ended.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QDialog

from git_gui.infrastructure.git_clone import CloneCancelled
from git_gui.presentation.widgets.clone_dialog import CloneDialog
from tests.presentation.window_helpers import blank_window

_CLONE_REPO = "git_gui.presentation.widgets.clone_dialog.clone_repo"
_URL = "https://example.com/user/repo.git"


def _open_clone_dialog(win, person) -> None:
    """Open the Clone dialog as the repo list does, `person(dialog)` doing what the person does."""

    def exec_(dialog):
        dialog.show()
        return person(dialog)

    with patch.object(CloneDialog, "exec", exec_):
        win._on_clone_requested()


def _wait_until_freed(qtbot, win) -> None:
    def dialog_is_gone():
        assert win.findChildren(CloneDialog) == [], (
            "the Clone dialog is still a child of the window"
        )

    qtbot.waitUntil(dialog_is_gone)


def _cancel(dialog: CloneDialog) -> QDialog.DialogCode:
    dialog._cancel_btn.click()
    return QDialog.DialogCode.Rejected


def test_a_dialog_cancelled_before_cloning_is_freed(qtbot):
    win = blank_window(qtbot)

    _open_clone_dialog(win, _cancel)

    _wait_until_freed(qtbot, win)


def test_a_dialog_closed_after_a_failed_clone_is_freed(qtbot):
    win = blank_window(qtbot)

    def give_up_after_the_failure(dialog):
        dialog._url_edit.setText(_URL)
        dialog._on_clone()
        qtbot.waitUntil(lambda: dialog._error_label.isVisible())
        return _cancel(dialog)

    with patch(_CLONE_REPO, side_effect=RuntimeError("boom")):
        _open_clone_dialog(win, give_up_after_the_failure)

    _wait_until_freed(qtbot, win)


def test_a_dialog_whose_clone_finished_is_freed_once_the_repo_is_handed_on(qtbot):
    win = blank_window(qtbot)
    opened: list[str] = []
    win._on_clone_completed = opened.append

    def wait_for_the_clone(dialog):
        dialog._url_edit.setText(_URL)
        with qtbot.waitSignal(dialog.accepted):
            dialog._on_clone()
        return QDialog.DialogCode.Accepted

    with patch(_CLONE_REPO):
        _open_clone_dialog(win, wait_for_the_clone)

    _wait_until_freed(qtbot, win)
    assert len(opened) == 1


def test_a_dialog_that_cloned_again_after_a_failure_is_freed(qtbot):
    """Each try has its own worker, and the dialog may go only when all of them have ended."""
    win = blank_window(qtbot)
    win._on_clone_completed = lambda _path: None

    def try_again_after_the_failure(dialog):
        dialog._url_edit.setText(_URL)
        dialog._on_clone()
        qtbot.waitUntil(lambda: dialog._error_label.isVisible())
        with qtbot.waitSignal(dialog.accepted):
            dialog._on_clone()
        return QDialog.DialogCode.Accepted

    with patch(_CLONE_REPO, side_effect=[RuntimeError("boom"), None]):
        _open_clone_dialog(win, try_again_after_the_failure)

    _wait_until_freed(qtbot, win)


@pytest.fixture
def git_stops():
    """Set by the test when git should finish dying; set at the end so no worker is left waiting."""
    stops = threading.Event()
    yield stops
    stops.set()


def test_a_dialog_cancelled_mid_clone_is_freed_when_the_clone_has_stopped(qtbot, git_stops):
    win = blank_window(qtbot)

    def clone_slow_to_stop(url, dest, on_progress=None, cancelled=None):
        cancelled.wait(5)
        git_stops.wait(5)
        raise CloneCancelled("cancelled")

    def cancel_mid_clone(dialog):
        dialog._url_edit.setText(_URL)
        dialog._on_clone()
        return _cancel(dialog)

    with patch(_CLONE_REPO, side_effect=clone_slow_to_stop):
        _open_clone_dialog(win, cancel_mid_clone)
        # Run any deletion that is already due, as the event loop does at its next turn.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert len(win.findChildren(CloneDialog)) == 1, "freed while its clone was still stopping"

        git_stops.set()
        _wait_until_freed(qtbot, win)
