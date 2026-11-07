"""A cancelled clone that could not remove what it wrote says so in the operations log.

The Clone dialog closes the moment the user cancels, and the clone stops git
and removes its files behind it. When a file was still held open, the error
went to that closed dialog: the partial clone stayed on disk unexplained, and
the next clone to the same place failed with "already exists".
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QDialog

from git_gui.infrastructure.git_clone import CloneCancelled
from git_gui.presentation.widgets.clone_dialog import CloneDialog
from tests.presentation.window_helpers import blank_window

_IN_USE = "[WinError 32] The process cannot access the file"


def _clone_that_cannot_clean_up(url, dest, on_progress=None, cancelled=None):
    cancelled.wait(5)
    raise CloneCancelled("cancelled", cleanup_error=PermissionError(_IN_USE))


def _start_and_cancel(dialog: CloneDialog) -> int:
    dialog._url_edit.setText("https://example.com/user/repo.git")
    dialog._on_clone()
    dialog.reject()
    return QDialog.DialogCode.Rejected


def test_a_cancelled_clone_that_left_files_behind_is_reported_in_the_log(qtbot):
    win = blank_window(qtbot)
    win._log_panel = MagicMock()

    with (
        patch(
            "git_gui.presentation.widgets.clone_dialog.clone_repo",
            side_effect=_clone_that_cannot_clean_up,
        ),
        patch.object(CloneDialog, "exec", _start_and_cancel),
    ):
        win._on_clone_requested()
        qtbot.waitUntil(lambda: win._log_panel.log_error.called)

    win._log_panel.expand.assert_called_once_with()
    message = win._log_panel.log_error.call_args.args[0]
    assert "repo" in message
    assert _IN_USE in message


@pytest.fixture
def git_stops():
    """Set by the test when git should finish dying; set at the end so no worker is left waiting."""
    stops = threading.Event()
    yield stops
    stops.set()


def test_a_cancelled_clone_that_stops_late_is_still_reported_before_its_dialog_is_freed(
    qtbot, git_stops
):
    """git can take longer to die than the dialog takes to close, and the report goes
    through that dialog, so the window may not delete it while the clone is stopping."""
    win = blank_window(qtbot)
    win._log_panel = MagicMock()

    def clone_slow_to_stop(url, dest, on_progress=None, cancelled=None):
        git_stops.wait(5)
        raise CloneCancelled("cancelled", cleanup_error=PermissionError(_IN_USE))

    with (
        patch(
            "git_gui.presentation.widgets.clone_dialog.clone_repo",
            side_effect=clone_slow_to_stop,
        ),
        patch.object(CloneDialog, "exec", _start_and_cancel),
    ):
        win._on_clone_requested()
        # Run any deletion that is already due, as the event loop does at its next turn.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        git_stops.set()
        qtbot.waitUntil(lambda: win._log_panel.log_error.called)

    assert _IN_USE in win._log_panel.log_error.call_args.args[0]
    qtbot.waitUntil(lambda: win.findChildren(CloneDialog) == [])
