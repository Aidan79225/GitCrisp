"""Which repo, branch and remote a remote operation acts on (RemoteOpQueueMixin)."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Branch
from git_gui.presentation.main_window import MainWindow

MODULE = "git_gui.presentation.main_window.remote_op_queue"
REJECTED = "! [rejected] feature -> feature (non-fast-forward)"


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
    win._commands = MagicMock()
    win._queries = _queries_on_branch("main", others=["feature"])
    return win


def _queries_on_branch(head: str | None, others: tuple[str, ...] | list[str] = ()) -> MagicMock:
    queries = MagicMock()
    branches = [Branch(name, False, False, "0" * 40) for name in others]
    if head is not None:
        branches.append(Branch(head, False, True, "1" * 40))
    queries.get_branches.execute.return_value = branches
    queries.list_local_branches_with_upstream.execute.return_value = []
    queries.list_remotes.execute.return_value = []
    return queries


def _wait_until_idle(qtbot, win: MainWindow) -> None:
    qtbot.waitUntil(lambda: not win._remote_running, timeout=2000)


def test_a_rejected_sidebar_push_offers_to_force_push_that_branch_not_head(qtbot):
    win = _make_window(qtbot)
    win._commands.push.execute.side_effect = RuntimeError(REJECTED)
    with (
        patch.object(win, "_reload"),
        patch(f"{MODULE}.QMessageBox.warning", return_value=QMessageBox.Yes) as warning,
    ):
        win._sidebar.branch_push_requested.emit("feature")
        qtbot.waitUntil(lambda: win._commands.force_push.execute.called, timeout=2000)
        _wait_until_idle(qtbot, win)

    win._commands.force_push.execute.assert_called_once_with("origin", "feature")
    assert "feature" in warning.call_args.args[2]


def test_a_rejected_push_force_pushes_in_the_repo_it_was_pushed_from(qtbot):
    win = _make_window(qtbot)
    pushed_from = win._commands
    switched = threading.Event()

    def _rejected_after_a_repo_switch(*_args):
        switched.wait(2)
        raise RuntimeError(REJECTED)

    pushed_from.push.execute.side_effect = _rejected_after_a_repo_switch
    with (
        patch.object(win, "_reload"),
        patch(f"{MODULE}.QMessageBox.warning", return_value=QMessageBox.Yes),
    ):
        win._on_push()
        win._commands = MagicMock()
        win._queries = _queries_on_branch("other")
        switched.set()
        qtbot.waitUntil(lambda: pushed_from.force_push.execute.called, timeout=2000)
        _wait_until_idle(qtbot, win)

    pushed_from.force_push.execute.assert_called_once_with("origin", "main")
    win._commands.force_push.execute.assert_not_called()


def test_a_rejected_tag_push_does_not_offer_to_force_push_a_branch(qtbot):
    win = _make_window(qtbot)
    with (
        patch.object(win, "_reload"),
        patch(f"{MODULE}.QMessageBox.warning") as warning,
    ):
        win._on_remote_error("Push tag v1", REJECTED)

    warning.assert_not_called()


def _cancel_after(win: MainWindow, replace_active_commands) -> MagicMock:
    """Start an op, swap the active bus as a repo switch would, then Cancel."""
    started_in = win._commands
    release = threading.Event()
    win._run_remote_op("Fetch --all --prune", lambda: release.wait(2))
    replace_active_commands()
    win._cancel_remote_op()
    release.set()
    return started_in


def test_cancel_after_a_repo_switch_stops_the_op_in_the_repo_it_started_in(qtbot):
    win = _make_window(qtbot)
    with patch.object(win, "_reload"):
        started_in = _cancel_after(win, lambda: setattr(win, "_commands", MagicMock()))
        _wait_until_idle(qtbot, win)

    started_in.cancel_remote_op.execute.assert_called_once_with()
    win._commands.cancel_remote_op.execute.assert_not_called()


def test_cancel_after_closing_the_last_repo_still_stops_the_op(qtbot):
    win = _make_window(qtbot)
    with patch.object(win, "_reload"):
        started_in = _cancel_after(win, lambda: setattr(win, "_commands", None))
        _wait_until_idle(qtbot, win)

    started_in.cancel_remote_op.execute.assert_called_once_with()
