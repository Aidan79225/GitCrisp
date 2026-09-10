from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.menus.git_menu import install_git_menu


def test_remote_branches_action_installed_and_opens(qtbot):
    win = QMainWindow()
    qtbot.addWidget(win)
    queries, commands = MagicMock(), MagicMock()

    install_git_menu(
        win,
        queries=queries,
        commands=commands,
        repo_workdir="/repo",
        on_open_submodule=lambda _p: None,
    )

    action = win._git_remote_branches_action
    assert action.text() == "Remote &Branches..."

    with patch("git_gui.presentation.menus.git_menu.RemoteBranchesDialog") as DlgCls:
        action.trigger()
    DlgCls.assert_called_once_with(queries, commands, win)
    DlgCls.return_value.exec.assert_called_once()
