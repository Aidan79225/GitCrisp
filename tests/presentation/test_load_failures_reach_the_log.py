"""A commit list or sidebar that cannot load says why in the operations log.

Both widgets clear what they showed and emit the reason, but nothing listened:
the user saw an empty pane and the reason went only to the file log.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from git_gui.presentation.main_window import MainWindow


def _make_window(qtbot) -> MainWindow:
    repo_store = MagicMock()
    repo_store.get_open_repos.return_value = []
    repo_store.get_recent_repos.return_value = []
    repo_store.get_active.return_value = None
    win = MainWindow(
        queries=None,
        commands=None,
        repo_store=repo_store,
        session_factory=lambda _p: (MagicMock(), MagicMock()),
    )
    qtbot.addWidget(win)
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
