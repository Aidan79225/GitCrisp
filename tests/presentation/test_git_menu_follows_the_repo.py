"""The window keeps exactly one Git menu as repos are opened and closed."""

from __future__ import annotations

from unittest.mock import MagicMock

from git_gui.presentation.main_window import MainWindow


def test_reinstalling_the_git_menu_leaves_one_on_the_bar(qtbot):
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

    win._install_git_menu()
    win._install_git_menu()

    titles = [a.text() for a in win.menuBar().actions()]
    assert titles.count("&Git") == 1
