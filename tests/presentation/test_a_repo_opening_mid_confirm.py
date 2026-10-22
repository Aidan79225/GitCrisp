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
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox

from git_gui.domain.entities import Branch, LocalBranchInfo, ResetMode, Worktree
from git_gui.presentation.dialogs.branches_dialog import BranchesDialog
from git_gui.presentation.main_window import MainWindow


def _session(_path: str = "/repo") -> tuple[MagicMock, MagicMock]:
    """A clean repo whose branches no other worktree holds."""
    queries = MagicMock()
    queries.find_worktree_for_branch.execute.return_value = None
    queries.get_working_tree.execute.return_value = []
    return queries, MagicMock()


@pytest.fixture
def win(qtbot) -> MainWindow:
    repo_store = MagicMock()
    repo_store.get_open_repos.return_value = []
    repo_store.get_recent_repos.return_value = []
    repo_store.get_active.return_value = None
    w = MainWindow(queries=None, commands=None, repo_store=repo_store, session_factory=_session)
    qtbot.addWidget(w)
    w._queries, w._commands = _session()
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


def _accepted_as_another_repo_opens(qtbot, win: MainWindow, dialog_cls: MagicMock) -> None:
    """Make the patched *dialog_cls* accept once the pending switch has landed."""
    dialog_cls.Accepted = QDialog.Accepted
    dialog_cls.return_value.exec.side_effect = _answering(qtbot, win, QDialog.Accepted)


def test_a_reset_to_commit_confirmed_as_another_repo_opens_resets_nothing(qtbot, win):
    asked_in = win._commands
    with patch("git_gui.presentation.main_window.reset_flow.ResetDialog") as dialog_cls:
        _accepted_as_another_repo_opens(qtbot, win, dialog_cls)
        dialog_cls.return_value.result_mode.return_value = ResetMode.HARD
        win._on_reset_to_commit("c" * 40, ResetMode.HARD)
    asked_in.reset_branch.execute.assert_not_called()
    win._commands.reset_branch.execute.assert_not_called()


@pytest.mark.parametrize(
    "restore",
    [
        lambda win, oid: win._on_reflog_restore_requested(oid, "HEAD@{1}"),
        lambda win, oid: win._on_log_action(oid),
    ],
    ids=["reflog-restore", "undo-link"],
)
def test_a_restore_confirmed_as_another_repo_opens_resets_nothing(qtbot, win, restore):
    oid = "c" * 40
    win._undoable[oid] = "Merge: topic into main"
    asked_in = win._commands
    with patch("git_gui.presentation.main_window.reflog_flow.ResetDialog") as dialog_cls:
        _accepted_as_another_repo_opens(qtbot, win, dialog_cls)
        dialog_cls.return_value.result_mode.return_value = ResetMode.HARD
        restore(win, oid)
    asked_in.reset_branch.execute.assert_not_called()
    win._commands.reset_branch.execute.assert_not_called()
    assert "Restore to ccccccc — skipped: another repo opened" in _log_text(win)


def test_a_merge_confirmed_as_another_repo_opens_merges_nothing(qtbot, win):
    win._queries.get_merge_analysis.execute.return_value = MagicMock(is_up_to_date=False)
    asked_in = win._commands
    flows = "git_gui.presentation.main_window.merge_rebase_flows"
    with (
        patch(f"{flows}.MergeDialog") as dialog_cls,
        patch(f"{flows}.ensure_identity", return_value=True),
    ):
        _accepted_as_another_repo_opens(qtbot, win, dialog_cls)
        win._on_merge_commit("c" * 40)
    asked_in.merge_commit.execute.assert_not_called()
    win._commands.merge_commit.execute.assert_not_called()


def test_a_tag_created_as_another_repo_opens_is_not_created_or_pushed(qtbot, win):
    asked_in = win._commands
    with patch("git_gui.presentation.main_window.tag_flows.CreateTagDialog") as dialog_cls:
        _accepted_as_another_repo_opens(qtbot, win, dialog_cls)
        dialog_cls.return_value.push_requested.return_value = True
        win._on_create_tag("c" * 40)
    for bus in (asked_in, win._commands):
        bus.create_tag.execute.assert_not_called()
        bus.push_tag.execute.assert_not_called()


def test_a_stash_drop_confirmed_as_another_repo_opens_drops_nothing(qtbot, win):
    asked_in = win._commands
    with patch.object(QMessageBox, "question", side_effect=_answering(qtbot, win, QMessageBox.Yes)):
        win._on_stash_drop(0)
    asked_in.drop_stash.execute.assert_not_called()
    win._commands.drop_stash.execute.assert_not_called()


def test_a_stash_confirmed_as_another_repo_opens_stashes_nothing(qtbot, win):
    asked_in = win._commands
    with (
        patch.object(QMessageBox, "question", side_effect=_answering(qtbot, win, QMessageBox.Yes)),
        patch("git_gui.presentation.main_window.stash_flows.ensure_identity", return_value=True),
    ):
        win._on_stash_requested()
    asked_in.stash.execute.assert_not_called()
    win._commands.stash.execute.assert_not_called()


def test_a_branch_created_as_another_repo_opens_is_not_created(qtbot, win):
    asked_in = win._commands
    with patch.object(QInputDialog, "getText", side_effect=_answering(qtbot, win, ("topic", True))):
        win._on_create_branch("c" * 40)
    for bus in (asked_in, win._commands):
        bus.create_branch.execute.assert_not_called()
        bus.checkout.execute.assert_not_called()


def test_a_branch_picked_as_another_repo_opens_is_not_checked_out(qtbot, win):
    win._queries.get_branches.execute.return_value = [_branch("feature"), _branch("topic")]
    asked_in = win._commands
    with patch("git_gui.presentation.main_window.branch_flows.BranchSelectDialog") as dialog_cls:
        _accepted_as_another_repo_opens(qtbot, win, dialog_cls)
        dialog_cls.return_value.selected.return_value = "topic"
        win._on_commit_double_clicked("a" * 40)
    asked_in.checkout.execute.assert_not_called()
    win._commands.checkout.execute.assert_not_called()


def _picking_the_first_row_as_another_repo_opens(qtbot, win: MainWindow, click):
    """A BranchesDialog.exec() that lets the switch land, then *click*s on row 0."""

    def _exec(dialog: BranchesDialog) -> int:
        _open_another_repo(qtbot, win)
        dialog._table.selectRow(0)
        click(dialog)
        return 0

    return _exec


@pytest.mark.parametrize(
    ("click", "op_name"),
    [
        (lambda dialog: dialog._on_checkout(), "Checkout feature"),
        (
            lambda dialog: dialog._on_checkout_in_new_worktree(),
            "Checkout feature in a new worktree",
        ),
    ],
    ids=["checkout", "checkout-in-new-worktree"],
)
def test_a_branch_picked_in_the_branches_dialog_as_another_repo_opens_is_not_checked_out(
    qtbot, win, click, op_name
):
    win._queries.list_local_branches_with_upstream.execute.return_value = [
        LocalBranchInfo("feature", None, "abc1234567", "work")
    ]
    win._install_git_menu()
    asked_in = win._commands
    picking = _picking_the_first_row_as_another_repo_opens(qtbot, win, click)
    with (
        patch.object(BranchesDialog, "exec", picking),
        patch.object(win, "_open_add_worktree_dialog") as add_worktree,
    ):
        win._git_branches_action.trigger()
    for bus in (asked_in, win._commands):
        bus.checkout.execute.assert_not_called()
        bus.checkout_remote_branch.execute.assert_not_called()
    add_worktree.assert_not_called()
    assert f"{op_name} — skipped: another repo opened" in _log_text(win)
