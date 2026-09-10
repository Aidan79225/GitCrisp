"""Stash flow integration: identity dialog gates the stash command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

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
    return win


def _wire_buses(win, identity=("Alice", "alice@example.com")):
    queries = MagicMock()
    queries.get_identity.execute.return_value = identity
    win._queries = queries

    commands = MagicMock()
    win._commands = commands
    return queries, commands


def test_stash_runs_when_identity_already_set(qtbot):
    win = _make_window(qtbot)
    queries, commands = _wire_buses(win)
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch.object(win, "_reload"),
        patch.object(win, "_get_current_branch", return_value="main"),
    ):
        win._on_stash_requested()
    commands.stash.execute.assert_called_once_with("WIP on main")


def test_stash_aborts_when_user_cancels_identity_dialog(qtbot):
    win = _make_window(qtbot)
    queries, commands = _wire_buses(win, identity=(None, None))
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch(
            "git_gui.presentation.main_window.stash_flows.ensure_identity",
            return_value=False,
        ),
        patch.object(win, "_reload"),
        patch.object(win, "_get_current_branch", return_value="main"),
    ):
        win._on_stash_requested()
    commands.stash.execute.assert_not_called()


def test_stash_runs_when_identity_set_via_dialog(qtbot):
    win = _make_window(qtbot)
    queries, commands = _wire_buses(win, identity=(None, None))
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch(
            "git_gui.presentation.main_window.stash_flows.ensure_identity",
            return_value=True,
        ),
        patch.object(win, "_reload"),
        patch.object(win, "_get_current_branch", return_value="main"),
    ):
        win._on_stash_requested()
    commands.stash.execute.assert_called_once_with("WIP on main")


def test_stash_skipped_when_user_says_no_to_stash_prompt(qtbot):
    """Existing behavior: top-level Yes/No prompt still gates the flow."""
    win = _make_window(qtbot)
    queries, commands = _wire_buses(win)
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.No),
        patch.object(win, "_reload"),
    ):
        win._on_stash_requested()
    commands.stash.execute.assert_not_called()
