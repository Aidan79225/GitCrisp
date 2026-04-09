from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.menus.git_menu import install_git_menu


def test_install_git_menu_adds_two_actions(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    install_git_menu(window, queries=None, commands=None, repo_workdir=None,
                     on_open_submodule=lambda p: None)
    bar = window.menuBar()
    titles = [a.text() for a in bar.actions()]
    assert "&Git" in titles
    git_menu = next(a.menu() for a in bar.actions() if a.text() == "&Git")
    item_texts = [a.text() for a in git_menu.actions()]
    assert "&Remotes..." in item_texts
    assert "&Submodules..." in item_texts
