"""Install a `Git` menu with `Remotes...` and `Submodules...` items."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialog, QMainWindow, QMenu

from git_gui.presentation.dialogs.branches_dialog import BranchesDialog
from git_gui.presentation.dialogs.remote_branches_dialog import RemoteBranchesDialog
from git_gui.presentation.dialogs.remote_dialog import RemoteDialog
from git_gui.presentation.dialogs.submodule_dialog import SubmoduleDialog


def install_git_menu(
    window: QMainWindow,
    queries,
    commands,
    repo_workdir: str | None,
    on_open_submodule: Callable[[str], None],
    on_open_worktrees_dialog: Callable[[], None] | None = None,
    on_open_reflog: Callable[[], None] | None = None,
    on_checkout_branch: Callable[[str], None] | None = None,
) -> None:
    """Add a `Git` menu with `Remotes...` and `Submodules...` actions,
    replacing the one an earlier call added.

    `on_open_submodule` is invoked with the absolute path of the submodule
    when the user clicks Open in the submodule dialog, and
    `on_checkout_branch` with the branch the user checks out in the Branches
    dialog.
    """
    _remove_previous_git_menu(window)
    bar = window.menuBar()
    git_menu = QMenu("&Git", window)
    bar.addMenu(git_menu)

    remote_action = QAction("&Remotes...", git_menu)

    def _open_remote() -> None:
        if queries is None or commands is None:
            return
        _run_and_discard(RemoteDialog(queries, commands, window))

    remote_action.triggered.connect(_open_remote)

    branches_action = QAction("&Branches...", git_menu)

    def _open_branches() -> None:
        if queries is None or commands is None:
            return
        dlg = BranchesDialog(queries, commands, window)
        dlg.set_worktree_paths(window._worktree_paths_by_branch)
        if on_checkout_branch is not None:
            dlg.checkout_requested.connect(on_checkout_branch)
        dlg.checkout_in_new_worktree_requested.connect(
            lambda branch: window._open_add_worktree_dialog(
                preselect_branch=branch, default_create=False
            )
        )
        _run_and_discard(dlg)

    branches_action.triggered.connect(_open_branches)

    remote_branches_action = QAction("Remote &Branches...", git_menu)

    def _open_remote_branches() -> None:
        if queries is None or commands is None:
            return
        _run_and_discard(RemoteBranchesDialog(queries, commands, window))

    remote_branches_action.triggered.connect(_open_remote_branches)

    submodule_action = QAction("&Submodules...", git_menu)

    def _open_submodule() -> None:
        if queries is None or commands is None or not repo_workdir:
            return
        d = SubmoduleDialog(queries, commands, repo_workdir, window)
        d.submoduleOpenRequested.connect(on_open_submodule)
        _run_and_discard(d)

    submodule_action.triggered.connect(_open_submodule)

    git_menu.addAction(remote_action)
    git_menu.addAction(branches_action)
    git_menu.addAction(remote_branches_action)
    git_menu.addAction(submodule_action)

    reflog_action = QAction("Ref&log...", git_menu)
    reflog_action.setStatusTip("Where HEAD has been — and how to get back there")

    def _open_reflog() -> None:
        if queries is None or on_open_reflog is None:
            return
        on_open_reflog()

    reflog_action.triggered.connect(_open_reflog)

    worktrees_action = QAction("&Worktrees...", git_menu)

    def _open_worktrees() -> None:
        if queries is None or commands is None or on_open_worktrees_dialog is None:
            return
        on_open_worktrees_dialog()

    worktrees_action.triggered.connect(_open_worktrees)
    git_menu.addAction(worktrees_action)
    git_menu.addSeparator()
    git_menu.addAction(reflog_action)

    window._git_menu = git_menu  # type: ignore[attr-defined]
    window._git_remote_action = remote_action  # type: ignore[attr-defined]
    window._git_branches_action = branches_action  # type: ignore[attr-defined]
    window._git_remote_branches_action = remote_branches_action  # type: ignore[attr-defined]
    window._git_submodule_action = submodule_action  # type: ignore[attr-defined]
    window._git_worktrees_action = worktrees_action  # type: ignore[attr-defined]


def _remove_previous_git_menu(window: QMainWindow) -> None:
    """Delete the menu an earlier install added, and its actions with it.

    Their slots hold that install's buses, so a menu that was only taken off
    the bar kept the previous repository open for as long as the window
    lived — on Windows with its pack files locked against deletion.
    """
    previous = getattr(window, "_git_menu", None)
    if previous is None:
        return
    window.menuBar().removeAction(previous.menuAction())
    previous.deleteLater()


def _run_and_discard(dialog: QDialog) -> None:
    """Run `dialog` modally, then delete it.

    Parented to the window, a finished dialog would otherwise live as long as
    the window and keep the session it was given open.
    """
    dialog.exec()
    dialog.deleteLater()
