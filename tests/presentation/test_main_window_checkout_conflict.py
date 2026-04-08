from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Branch
from git_gui.presentation.main_window import MainWindow


def _make_window(qtbot):
    repo_store = MagicMock()
    repo_store.get_open_repos.return_value = []
    repo_store.get_recent_repos.return_value = []
    repo_store.get_active.return_value = None
    win = MainWindow(queries=None, commands=None, repo_store=repo_store)
    qtbot.addWidget(win)
    return win


def _wire_buses(win):
    queries = MagicMock()
    commands = MagicMock()
    queries.get_branches.execute.return_value = [
        Branch("feature", False, False, "abc"),
        Branch("origin/feature", True, False, "abc"),
    ]
    win._queries = queries
    win._commands = commands
    return queries, commands


def test_conflict_yes_resets_local(qtbot):
    win = _make_window(qtbot)
    queries, commands = _wire_buses(win)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
         patch.object(win, "_reload"):
        win._on_checkout_branch("origin/feature")
    commands.checkout.execute.assert_called_once_with("feature")
    commands.reset_branch_to_ref.execute.assert_called_once_with(
        "feature", "origin/feature"
    )


def test_conflict_cancel_does_nothing(qtbot):
    win = _make_window(qtbot)
    queries, commands = _wire_buses(win)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel), \
         patch.object(win, "_reload"):
        win._on_checkout_branch("origin/feature")
    commands.checkout.execute.assert_not_called()
    commands.reset_branch_to_ref.execute.assert_not_called()
    commands.checkout_remote_branch.execute.assert_not_called()


def test_no_conflict_falls_through(qtbot):
    win = _make_window(qtbot)
    queries, commands = _wire_buses(win)
    queries.get_branches.execute.return_value = [
        Branch("origin/feature", True, False, "abc"),
    ]
    with patch.object(win, "_reload"):
        win._on_checkout_branch("origin/feature")
    commands.checkout_remote_branch.execute.assert_called_once_with("origin/feature")
