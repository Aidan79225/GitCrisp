"""Deleting a branch checked out in a linked worktree: GitCrisp offers to
remove the worktree first, then deletes the branch (instead of surfacing
libgit2's "current HEAD of a linked repository" error)."""

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Worktree
from git_gui.presentation.main_window import MainWindow


def _make_window(qtbot):
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
    win._queries = MagicMock()
    win._commands = MagicMock()
    return win


def _worktree(branch: str, *, is_main: bool = False, path: str = "/repo/.wt/agent") -> Worktree:
    return Worktree(
        path=path,
        branch=branch,
        head_sha="a" * 40,
        is_locked=False,
        lock_reason=None,
        is_bare=False,
        is_main=is_main,
    )


def test_confirm_removes_worktree_then_deletes_branch(qtbot):
    win = _make_window(qtbot)
    win._queries.find_worktree_for_branch.execute.return_value = _worktree("wt-branch")
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch.object(win, "_reload"),
        patch.object(win, "_load_worktrees_for_active_repo"),
    ):
        win._on_delete_branch("wt-branch")
    win._commands.remove_worktree.execute.assert_called_once_with("/repo/.wt/agent", force=False)
    win._commands.delete_branch.execute.assert_called_once_with("wt-branch")


def test_cancel_aborts_without_removing_or_deleting(qtbot):
    win = _make_window(qtbot)
    win._queries.find_worktree_for_branch.execute.return_value = _worktree("wt-branch")
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel),
        patch.object(win, "_reload"),
    ):
        win._on_delete_branch("wt-branch")
    win._commands.remove_worktree.execute.assert_not_called()
    win._commands.delete_branch.execute.assert_not_called()


def test_branch_not_in_worktree_deletes_directly(qtbot):
    win = _make_window(qtbot)
    win._queries.find_worktree_for_branch.execute.return_value = None
    with patch.object(win, "_reload"):
        win._on_delete_branch("plain")
    win._commands.remove_worktree.execute.assert_not_called()
    win._commands.delete_branch.execute.assert_called_once_with("plain")


def test_main_worktree_branch_is_not_offered_removal(qtbot):
    """The branch checked out in the MAIN worktree can't have its worktree
    removed; fall through to a plain delete (which surfaces git's own error)."""
    win = _make_window(qtbot)
    win._queries.find_worktree_for_branch.execute.return_value = _worktree("develop", is_main=True)
    with patch.object(win, "_reload"):
        win._on_delete_branch("develop")
    win._commands.remove_worktree.execute.assert_not_called()
    win._commands.delete_branch.execute.assert_called_once_with("develop")


def test_dirty_worktree_offers_force_then_removes(qtbot):
    win = _make_window(qtbot)
    win._queries.find_worktree_for_branch.execute.return_value = _worktree("wt-branch")

    class WorktreeDirtyError(Exception):
        pass

    win._commands.remove_worktree.execute.side_effect = [WorktreeDirtyError("dirty"), None]
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch.object(win, "_ask_force_remove_worktree", return_value=True),
        patch.object(win, "_reload"),
        patch.object(win, "_load_worktrees_for_active_repo"),
    ):
        win._on_delete_branch("wt-branch")
    assert win._commands.remove_worktree.execute.call_count == 2
    win._commands.remove_worktree.execute.assert_any_call("/repo/.wt/agent", force=True)
    win._commands.delete_branch.execute.assert_called_once_with("wt-branch")


def test_dirty_worktree_force_declined_aborts(qtbot):
    win = _make_window(qtbot)
    win._queries.find_worktree_for_branch.execute.return_value = _worktree("wt-branch")

    class WorktreeDirtyError(Exception):
        pass

    win._commands.remove_worktree.execute.side_effect = WorktreeDirtyError("dirty")
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch.object(win, "_ask_force_remove_worktree", return_value=False),
        patch.object(win, "_reload"),
    ):
        win._on_delete_branch("wt-branch")
    win._commands.delete_branch.execute.assert_not_called()
