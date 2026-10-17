"""Resetting a branch to its remote must not destroy work from another branch.

Both reset offers check the local branch out and then hard-reset it. A
checkout carries uncommitted edits over from the branch the user was on, so
the hard reset would wipe them, although the prompt only warns about changes
on the branch being reset. Those resets are refused until the edits are
committed or stashed.
"""

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import (
    Branch,
    FileDelta,
    FileStatus,
    LocalBranchInfo,
    StagingState,
)
from git_gui.presentation.main_window import MainWindow

_DLG = "git_gui.presentation.main_window.branch_flows.BranchSelectDialog"
_EDIT = FileStatus("a.txt", StagingState.UNSTAGED, FileDelta.MODIFIED)
_UNTRACKED = FileStatus("scratch.txt", StagingState.UNTRACKED, FileDelta.ADDED)


def _make_window(qtbot, *, feature_is_head: bool, working_tree: list[FileStatus]):
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
    win._graph = MagicMock()
    win._log_panel = MagicMock()
    win._queries.get_branches.execute.return_value = [
        Branch("master", False, not feature_is_head, "m1"),
        Branch("feature", False, feature_is_head, "f1"),
        Branch("origin/feature", True, False, "f2"),
    ]
    win._queries.find_worktree_for_branch.execute.return_value = None
    win._queries.get_working_tree.execute.return_value = working_tree
    win._queries.list_local_branches_with_upstream.execute.return_value = [
        LocalBranchInfo("feature", "origin/feature", "f1", "msg"),
    ]
    return win


def _checkout_remote(win) -> MagicMock:
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as question,
        patch.object(win, "_reload"),
    ):
        win._on_checkout_branch("origin/feature")
    return question


def _double_click_feature(win) -> MagicMock:
    with (
        patch(_DLG),
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as question,
        patch.object(win, "_reload"),
    ):
        win._on_commit_double_clicked("f1")
    return question


def test_remote_checkout_refuses_to_reset_over_edits_from_another_branch(qtbot):
    win = _make_window(qtbot, feature_is_head=False, working_tree=[_EDIT])
    question = _checkout_remote(win)
    question.assert_not_called()
    win._commands.checkout.execute.assert_not_called()
    win._commands.reset_branch_to_ref.execute.assert_not_called()
    assert "Commit or stash" in win._log_panel.log_error.call_args.args[0]


def test_remote_checkout_still_resets_the_branch_it_is_on(qtbot):
    """Uncommitted changes on the branch itself are what the prompt warns about."""
    win = _make_window(qtbot, feature_is_head=True, working_tree=[_EDIT])
    question = _checkout_remote(win)
    question.assert_called_once()
    win._commands.reset_branch_to_ref.execute.assert_called_once_with("feature", "origin/feature")


def test_untracked_files_do_not_block_the_reset(qtbot):
    """A hard reset leaves untracked files alone."""
    win = _make_window(qtbot, feature_is_head=False, working_tree=[_UNTRACKED])
    _checkout_remote(win)
    win._commands.reset_branch_to_ref.execute.assert_called_once_with("feature", "origin/feature")


def test_double_click_does_not_offer_a_reset_over_edits_from_another_branch(qtbot):
    win = _make_window(qtbot, feature_is_head=False, working_tree=[_EDIT])
    question = _double_click_feature(win)
    win._commands.checkout.execute.assert_called_once_with("feature")
    question.assert_not_called()
    win._commands.reset_branch_to_ref.execute.assert_not_called()


def test_double_click_on_the_current_branch_still_offers_the_reset(qtbot):
    win = _make_window(qtbot, feature_is_head=True, working_tree=[_EDIT])
    question = _double_click_feature(win)
    question.assert_called_once()
    win._commands.reset_branch_to_ref.execute.assert_called_once_with("feature", "origin/feature")
