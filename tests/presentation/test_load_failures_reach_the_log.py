"""A commit list, sidebar or changed-files list that cannot load says why in
the operations log.

Each widget clears what it showed and emit the reason, but nothing listened:
the user saw an empty pane and the reason went only to the file log.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from git_gui.presentation.main_window import MainWindow
from tests.presentation.window_helpers import blank_window


def _make_window(qtbot) -> MainWindow:
    win = blank_window(qtbot)
    win._log_panel = MagicMock()
    return win


def test_a_failed_commit_list_load_is_reported(qtbot):
    win = _make_window(qtbot)

    win._graph.load_failed.emit("object not found")

    win._log_panel.expand.assert_called_once_with()
    message = win._log_panel.log_error.call_args.args[0]
    assert "commits" in message
    assert "object not found" in message


def test_a_failed_sidebar_load_is_reported(qtbot):
    win = _make_window(qtbot)

    win._sidebar.load_failed.emit("annotated tag on a tree")

    win._log_panel.expand.assert_called_once_with()
    message = win._log_panel.log_error.call_args.args[0]
    assert "branches and tags" in message
    assert "annotated tag on a tree" in message


def test_a_failed_changed_files_load_is_reported(qtbot):
    win = _make_window(qtbot)

    win._working_tree.load_failed.emit("index file corrupt")

    win._log_panel.expand.assert_called_once_with()
    message = win._log_panel.log_error.call_args.args[0]
    assert "changed files" in message
    assert "index file corrupt" in message


def test_a_first_parent_choice_that_could_not_be_saved_is_reported(qtbot):
    win = _make_window(qtbot)

    win._graph.setting_save_failed.emit("Access is denied")

    win._log_panel.expand.assert_called_once_with()
    message = win._log_panel.log_error.call_args.args[0]
    assert "first-parent" in message
    assert "Access is denied" in message
