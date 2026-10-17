"""Checking out a branch that another worktree has checked out.

libgit2 rewrites the working tree and index before it refuses to move HEAD
onto such a branch, so the check has to come first: GitCrisp switches to the
worktree that holds the branch instead of checking it out here.
"""

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Branch, Worktree
from git_gui.presentation.main_window import MainWindow

_DLG = "git_gui.presentation.main_window.branch_flows.BranchSelectDialog"
_WT_PATH = "/repo/.wt/feature"


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
    win._graph = MagicMock()
    win._queries.list_local_branches_with_upstream.execute.return_value = []
    return win


def _worktree(branch: str, *, is_main: bool = False) -> Worktree:
    return Worktree(
        path=_WT_PATH,
        branch=branch,
        head_sha="a" * 40,
        is_locked=False,
        lock_reason=None,
        is_bare=False,
        is_main=is_main,
    )


def _held_elsewhere(win, *branches: Branch) -> None:
    win._queries.get_branches.execute.return_value = list(branches)
    win._queries.find_worktree_for_branch.execute.return_value = _worktree("feature")


def test_checkout_of_a_branch_held_by_a_linked_worktree_switches_to_it(qtbot):
    win = _make_window(qtbot)
    _held_elsewhere(win, Branch("feature", False, False, "f1"))
    with patch.object(win, "_switch_repo") as switch, patch.object(win, "_reload"):
        win._on_checkout_branch("feature")
    win._commands.checkout.execute.assert_not_called()
    switch.assert_called_once_with(_WT_PATH)


def test_double_click_on_a_branch_held_by_a_linked_worktree_switches_to_it(qtbot):
    win = _make_window(qtbot)
    _held_elsewhere(win, Branch("feature", False, False, "f1"))
    with patch(_DLG), patch.object(win, "_switch_repo") as switch, patch.object(win, "_reload"):
        win._on_commit_double_clicked("f1")
    win._commands.checkout.execute.assert_not_called()
    switch.assert_called_once_with(_WT_PATH)


def test_remote_checkout_whose_local_is_held_elsewhere_switches_without_resetting(qtbot):
    win = _make_window(qtbot)
    _held_elsewhere(
        win,
        Branch("feature", False, False, "f1"),
        Branch("origin/feature", True, False, "f2"),
    )
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch.object(win, "_switch_repo") as switch,
        patch.object(win, "_reload"),
    ):
        win._on_checkout_branch("origin/feature")
    win._commands.checkout.execute.assert_not_called()
    win._commands.reset_branch_to_ref.execute.assert_not_called()
    switch.assert_called_once_with(_WT_PATH)


def test_a_branch_held_by_the_main_worktree_switches_there_too(qtbot):
    """A session opened on a linked worktree cannot check out the main
    worktree's branch either."""
    win = _make_window(qtbot)
    win._queries.get_branches.execute.return_value = [Branch("master", False, False, "m1")]
    win._queries.find_worktree_for_branch.execute.return_value = _worktree("master", is_main=True)
    with patch.object(win, "_switch_repo") as switch, patch.object(win, "_reload"):
        win._on_checkout_branch("master")
    win._commands.checkout.execute.assert_not_called()
    switch.assert_called_once_with(_WT_PATH)


def test_the_branch_already_checked_out_here_is_not_sent_elsewhere(qtbot):
    win = _make_window(qtbot)
    win._queries.get_branches.execute.return_value = [Branch("feature", False, True, "f1")]
    win._queries.find_worktree_for_branch.execute.return_value = _worktree("feature", is_main=True)
    with patch.object(win, "_switch_repo") as switch, patch.object(win, "_reload"):
        win._on_checkout_branch("feature")
    switch.assert_not_called()
    win._commands.checkout.execute.assert_called_once_with("feature")
