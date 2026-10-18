"""A MainWindow with no repo open, for tests that drive one flow on it."""

from __future__ import annotations

from unittest.mock import MagicMock

from git_gui.presentation.main_window import MainWindow


def empty_repo_store() -> MagicMock:
    store = MagicMock()
    store.get_open_repos.return_value = []
    store.get_recent_repos.return_value = []
    store.get_active.return_value = None
    return store


def blank_window(qtbot, repo_store: MagicMock | None = None) -> MainWindow:
    """No buses, and a session factory that never touches git."""
    win = MainWindow(
        queries=None,
        commands=None,
        repo_store=repo_store or empty_repo_store(),
        session_factory=lambda _p: (MagicMock(), MagicMock()),
    )
    qtbot.addWidget(win)
    return win


def wired_window(qtbot, repo_store: MagicMock | None = None) -> MainWindow:
    """A blank window whose query and command buses are MagicMocks."""
    win = blank_window(qtbot, repo_store)
    win._queries = MagicMock()
    win._commands = MagicMock()
    return win
