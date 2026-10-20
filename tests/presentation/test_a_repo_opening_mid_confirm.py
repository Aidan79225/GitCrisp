"""An action the user confirmed runs in the repo they were asked about, or not at all.

A confirmation box runs a nested event loop, so a repo switch that was already
on its way (an open on a network share can take seconds) lands while the box
is up and replaces the window's buses. The flows read the bus only after the
box closed, so what the user agreed to for one repo ran in the other: a
remote branch or tag deleted from another project, a hard reset of another
worktree's uncommitted edits.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Branch, Worktree
from git_gui.presentation.main_window import MainWindow


@pytest.fixture
def win(qtbot) -> MainWindow:
    repo_store = MagicMock()
    repo_store.get_open_repos.return_value = []
    repo_store.get_recent_repos.return_value = []
    repo_store.get_active.return_value = None
    w = MainWindow(
        queries=None,
        commands=None,
        repo_store=repo_store,
        session_factory=lambda _p: (MagicMock(), MagicMock()),
    )
    qtbot.addWidget(w)
    w._queries = MagicMock()
    w._commands = MagicMock()
    w._queries.find_worktree_for_branch.execute.return_value = None
    w._queries.get_working_tree.execute.return_value = []
    return w


def _open_another_repo(qtbot, win: MainWindow) -> None:
    """Let a pending repo switch land now, as the box's nested loop would."""
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._switch_repo("/other")


def _answering(qtbot, win: MainWindow, answer):
    def _ask(*_args, **_kwargs):
        _open_another_repo(qtbot, win)
        return answer

    return _ask


def _branch(name: str, oid: str = "a" * 40, *, remote: bool = False) -> Branch:
    return Branch(name=name, is_remote=remote, is_head=False, target_oid=oid)


def _log_text(win: MainWindow) -> str:
    return win._log_panel._body.toPlainText()


def test_a_remote_branch_delete_confirmed_as_another_repo_opens_deletes_nothing(qtbot, win):
    asked_in = win._commands
    with patch.object(QMessageBox, "question", side_effect=_answering(qtbot, win, QMessageBox.Yes)):
        win._on_delete_remote_branch("origin", "topic")
    asked_in.delete_remote_branch.execute.assert_not_called()
    win._commands.delete_remote_branch.execute.assert_not_called()


def test_the_user_is_told_why_a_confirmed_delete_did_not_run(qtbot, win):
    with patch.object(QMessageBox, "question", side_effect=_answering(qtbot, win, QMessageBox.Yes)):
        win._on_delete_remote_branch("origin", "topic")
    assert "Delete origin/topic — skipped: another repo opened" in _log_text(win)


def test_a_reset_to_remote_confirmed_as_another_repo_opens_resets_nothing(qtbot, win):
    win._queries.get_branches.execute.return_value = [
        _branch("feature"),
        _branch("origin/feature", "b" * 40, remote=True),
    ]
    asked_in = win._commands
    with patch.object(QMessageBox, "question", side_effect=_answering(qtbot, win, QMessageBox.Yes)):
        win._on_checkout_branch("origin/feature")
    for bus in (asked_in, win._commands):
        bus.checkout.execute.assert_not_called()
        bus.reset_branch_to_ref.execute.assert_not_called()


def test_a_diverged_branch_reset_confirmed_as_another_repo_opens_resets_nothing(qtbot, win):
    feature = _branch("feature")
    win._queries.list_local_branches_with_upstream.execute.return_value = [
        SimpleNamespace(name="feature", upstream="origin/feature")
    ]
    asked_in = win._commands
    with patch.object(QMessageBox, "question", side_effect=_answering(qtbot, win, QMessageBox.Yes)):
        win._switch_to_branch(feature, [feature, _branch("origin/feature", "b" * 40, remote=True)])
    asked_in.reset_branch_to_ref.execute.assert_not_called()
    win._commands.reset_branch_to_ref.execute.assert_not_called()


def test_a_branch_delete_confirmed_as_another_repo_opens_deletes_nothing(qtbot, win):
    asked_in = win._commands
    with patch.object(QMessageBox, "question", side_effect=_answering(qtbot, win, QMessageBox.Yes)):
        win._on_delete_branch("topic")
    asked_in.delete_branch.execute.assert_not_called()
    win._commands.delete_branch.execute.assert_not_called()


def _linked_worktree(branch: str) -> Worktree:
    return Worktree(
        path="/repo/.wt/agent",
        branch=branch,
        head_sha="a" * 40,
        is_locked=False,
        lock_reason=None,
        is_bare=False,
        is_main=False,
    )


def test_a_worktree_removal_confirmed_as_another_repo_opens_removes_nothing(qtbot, win):
    win._queries.find_worktree_for_branch.execute.return_value = _linked_worktree("topic")
    asked_in = win._commands
    with patch.object(QMessageBox, "question", side_effect=_answering(qtbot, win, QMessageBox.Yes)):
        win._on_delete_branch("topic")
    for bus in (asked_in, win._commands):
        bus.remove_worktree.execute.assert_not_called()
        bus.delete_branch.execute.assert_not_called()


def test_a_force_removal_confirmed_as_another_repo_opens_removes_nothing(qtbot, win):
    class WorktreeDirtyError(Exception):
        pass

    win._queries.find_worktree_for_branch.execute.return_value = _linked_worktree("topic")
    asked_in = win._commands
    asked_in.remove_worktree.execute.side_effect = WorktreeDirtyError("dirty")
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch.object(win, "_ask_force_remove_worktree", side_effect=_answering(qtbot, win, True)),
        patch.object(win, "_load_worktrees_for_active_repo"),
    ):
        win._on_delete_branch("topic")
    assert asked_in.remove_worktree.execute.call_count == 1  # the unforced try
    win._commands.remove_worktree.execute.assert_not_called()
    win._commands.delete_branch.execute.assert_not_called()


def _choosing(qtbot, win: MainWindow, label: str):
    """A box.exec() that lets the switch land, then clicks *label*."""

    def _exec(*_args):
        _open_another_repo(qtbot, win)
        box = win.findChildren(QMessageBox)[-1]
        next(b for b in box.buttons() if b.text() == label).click()
        return 0

    return _exec


def test_a_tag_delete_confirmed_as_another_repo_opens_deletes_nothing(qtbot, win):
    win._repo_path = "/repo"
    win._remote_tag_cache = MagicMock()
    win._remote_tag_cache.load.return_value = {"origin": ["v1"]}
    asked_in = win._commands
    with patch.object(QMessageBox, "exec", side_effect=_choosing(qtbot, win, "Local + remote")):
        win._on_delete_tag("v1")
    for bus in (asked_in, win._commands):
        bus.delete_tag.execute.assert_not_called()
        bus.delete_remote_tag.execute.assert_not_called()


def test_a_local_tag_delete_confirmed_as_another_repo_opens_deletes_nothing(qtbot, win):
    asked_in = win._commands
    with patch.object(QMessageBox, "question", side_effect=_answering(qtbot, win, QMessageBox.Yes)):
        win._on_delete_tag("v1")
    asked_in.delete_tag.execute.assert_not_called()
    win._commands.delete_tag.execute.assert_not_called()
