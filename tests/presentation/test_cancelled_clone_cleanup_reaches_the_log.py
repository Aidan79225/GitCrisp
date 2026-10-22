"""A cancelled clone that could not remove what it wrote says so in the operations log.

The Clone dialog closes the moment the user cancels, and the clone stops git
and removes its files behind it. When a file was still held open, the error
went to that closed dialog: the partial clone stayed on disk unexplained, and
the next clone to the same place failed with "already exists".
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
