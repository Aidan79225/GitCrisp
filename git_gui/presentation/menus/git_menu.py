"""Install a `Git` menu with `Remotes...` and `Submodules...` items."""
from __future__ import annotations
from typing import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QMenu

from git_gui.presentation.dialogs.remote_dialog import RemoteDialog
from git_gui.presentation.dialogs.submodule_dialog import SubmoduleDialog


def install_git_menu(
    window: QMainWindow,
    queries,
    commands,
    repo_workdir: str | None,
    on_open_submodule: Callable[[str], None],
) -> None:
    """Add a `Git` menu with `Remotes...` and `Submodules...` actions.

    `on_open_submodule` is invoked with the absolute path of the submodule
    when the user clicks Open in the submodule dialog.
    """
    bar = window.menuBar()
    git_menu = QMenu("&Git", window)
    bar.addMenu(git_menu)

    remote_action = QAction("&Remotes...", window)

    def _open_remote() -> None:
        if queries is None or commands is None:
            return
        RemoteDialog(queries, commands, window).exec()

    remote_action.triggered.connect(_open_remote)

    submodule_action = QAction("&Submodules...", window)

    def _open_submodule() -> None:
        if queries is None or commands is None or not repo_workdir:
            return
        d = SubmoduleDialog(queries, commands, repo_workdir, window)
        d.submoduleOpenRequested.connect(on_open_submodule)
        d.exec()

    submodule_action.triggered.connect(_open_submodule)

    git_menu.addAction(remote_action)
    git_menu.addAction(submodule_action)

    window._git_menu = git_menu  # type: ignore[attr-defined]
    window._git_remote_action = remote_action  # type: ignore[attr-defined]
    window._git_submodule_action = submodule_action  # type: ignore[attr-defined]
