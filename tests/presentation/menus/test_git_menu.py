from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.menus.git_menu import install_git_menu


def test_install_git_menu_adds_two_actions(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    install_git_menu(
        window,
        queries=None,
        commands=None,
        repo_workdir=None,
        on_open_submodule=lambda p: None,
        on_open_worktrees_dialog=lambda: None,
        on_open_reflog=lambda: None,
        on_checkout_branch=lambda _b: None,
    )
    bar = window.menuBar()
    titles = [a.text() for a in bar.actions()]
    assert "&Git" in titles
    git_menu = next(a.menu() for a in bar.actions() if a.text() == "&Git")
    item_texts = [a.text() for a in git_menu.actions()]
    assert "&Remotes..." in item_texts
    assert "&Submodules..." in item_texts


def test_checkout_in_the_branches_dialog_reaches_the_windows_checkout(qtbot):
    from unittest.mock import MagicMock, patch

    from git_gui.domain.entities import LocalBranchInfo
    from git_gui.presentation.dialogs.branches_dialog import BranchesDialog

    window = QMainWindow()
    window._worktree_paths_by_branch = {}
    qtbot.addWidget(window)
    queries = MagicMock()
    queries.list_local_branches_with_upstream.execute.return_value = [
        LocalBranchInfo("feat", None, "abc1234567", "work"),
    ]
    checked_out: list[str] = []
    install_git_menu(
        window,
        queries=queries,
        commands=MagicMock(),
        repo_workdir=None,
        on_open_submodule=lambda p: None,
        on_open_worktrees_dialog=lambda: None,
        on_open_reflog=lambda: None,
        on_checkout_branch=checked_out.append,
    )

    def _check_out_first_row(dialog: BranchesDialog) -> int:
        dialog._table.selectRow(0)
        dialog._checkout_btn.click()
        return 0

    with patch.object(BranchesDialog, "exec", _check_out_first_row):
        window._git_branches_action.trigger()

    assert checked_out == ["feat"]


def _install(window: QMainWindow, *, session, repo_workdir: str | None, **callbacks) -> None:
    defaults = {
        "on_open_submodule": lambda _p: None,
        "on_open_worktrees_dialog": lambda: None,
        "on_open_reflog": lambda: None,
        "on_checkout_branch": lambda _b: None,
    }
    install_git_menu(
        window,
        queries=session,
        commands=session,
        repo_workdir=repo_workdir,
        **{**defaults, **callbacks},
    )


def _enabled_items(window: QMainWindow) -> dict[str, bool]:
    return {a.text(): a.isEnabled() for a in window._git_menu.actions() if not a.isSeparator()}


def test_with_no_repo_open_every_git_item_is_disabled_rather_than_dead(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    _install(window, session=None, repo_workdir=None)
    assert not any(_enabled_items(window).values())


def test_with_a_repo_open_every_git_item_is_enabled(qtbot):
    from unittest.mock import MagicMock

    window = QMainWindow()
    qtbot.addWidget(window)
    _install(window, session=MagicMock(), repo_workdir="/repo")
    assert all(_enabled_items(window).values())


def test_the_reflog_item_calls_back_without_arguments(qtbot):
    from unittest.mock import MagicMock

    window = QMainWindow()
    qtbot.addWidget(window)
    opened = MagicMock()
    _install(window, session=MagicMock(), repo_workdir="/repo", on_open_reflog=opened)
    next(a for a in window._git_menu.actions() if a.text() == "Ref&log...").trigger()
    opened.assert_called_once_with()
