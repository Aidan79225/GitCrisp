"""A worktree added from the Add Worktree dialog goes to the repo it was opened for.

The dialog is modal and runs a nested event loop, so a repo switch already on
its way lands while it is up. Add read the window's buses only when it was
clicked, so the branch and the worktree the user filled in for one repo were
created in the other.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from git_gui.presentation.dialogs.add_worktree_dialog import AddWorktreeDialog
from git_gui.presentation.main_window import MainWindow
from tests.presentation.window_helpers import empty_repo_store

_PAYLOAD = {
    "location": "/tmp/repo-feature",
    "branch": "feature",
    "create_new": True,
    "base_ref": "master",
    "switch_after": False,
}


def _session(_path: str) -> tuple[MagicMock, MagicMock]:
    return MagicMock(), MagicMock()


@pytest.fixture
def win(qtbot) -> MainWindow:
    w = MainWindow(
        queries=None, commands=None, repo_store=empty_repo_store(), session_factory=_session
    )
    qtbot.addWidget(w)
    w._queries, w._commands = _session("/repo")
    w._repo_path = "/repo"
    return w


def _adding_once_another_repo_opens(qtbot, win: MainWindow):
    def _exec(dialog: AddWorktreeDialog) -> int:
        with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
            win._switch_repo("/other")
        dialog.add_requested.emit(dict(_PAYLOAD))
        return 1

    return _exec


def test_a_worktree_added_as_another_repo_opens_is_added_nowhere(qtbot, win, monkeypatch):
    asked_in = win._commands
    monkeypatch.setattr(AddWorktreeDialog, "exec", _adding_once_another_repo_opens(qtbot, win))

    win._open_add_worktree_dialog(preselect_branch=None, default_create=False)
    qtbot.wait(300)

    assert win._commands is not asked_in
    asked_in.add_worktree.execute.assert_not_called()
    win._commands.add_worktree.execute.assert_not_called()


def test_the_user_is_told_why_the_worktree_was_not_added(qtbot, win, monkeypatch):
    monkeypatch.setattr(AddWorktreeDialog, "exec", _adding_once_another_repo_opens(qtbot, win))

    win._open_add_worktree_dialog(preselect_branch=None, default_create=False)

    assert "Add worktree feature — skipped: another repo opened" in (
        win._log_panel._body.toPlainText()
    )


def test_a_worktree_added_in_the_same_repo_is_added(qtbot, win, monkeypatch):
    def _exec(dialog: AddWorktreeDialog) -> int:
        dialog.add_requested.emit(dict(_PAYLOAD))
        return 1

    monkeypatch.setattr(AddWorktreeDialog, "exec", _exec)

    win._open_add_worktree_dialog(preselect_branch=None, default_create=False)

    qtbot.waitUntil(lambda: win._commands.add_worktree.execute.called, timeout=2000)
