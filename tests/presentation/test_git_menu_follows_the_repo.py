"""The window keeps exactly one Git menu as repos are opened and closed."""

from __future__ import annotations

from tests.presentation.window_helpers import blank_window


def test_reinstalling_the_git_menu_leaves_one_on_the_bar(qtbot):
    win = blank_window(qtbot)

    win._install_git_menu()
    win._install_git_menu()

    titles = [a.text() for a in win.menuBar().actions()]
    assert titles.count("&Git") == 1
