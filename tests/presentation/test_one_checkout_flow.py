"""Every way of checking out a branch goes through one flow.

The sidebar's context-menu Checkout went through SmartCheckout, but only
after a repo switch had built one: at launch it went through the window's
checkout flow, and after a switch it bypassed it, so a successful checkout
was neither logged nor followed by a reload. The flow asks which worktree
holds the branch before touching this one, and opens that worktree instead.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow


@pytest.fixture
def main_with_feat_worktree(tmp_path) -> tuple[Path, Path]:
    """`main` on master, branch `feat` (which changes a.txt) checked out in `wt`,
    and an unheld branch `topic`."""
    main = tmp_path / "main"
    repo = pygit2.init_repository(str(main), initial_head="master")
    sig = pygit2.Signature("T", "t@e.com")
    (main / "a.txt").write_text("master\n")
    repo.index.add("a.txt")
    repo.index.write()
    base = repo.create_commit("refs/heads/master", sig, sig, "init", repo.index.write_tree(), [])
    repo.create_branch("topic", repo[base])
    blob = repo.create_blob(b"feat\n")
    builder = repo.TreeBuilder(repo[base].tree)
    builder.insert("a.txt", blob, pygit2.enums.FileMode.BLOB)
    repo.create_commit("refs/heads/feat", sig, sig, "feat", builder.write(), [base])
    wt = tmp_path / "wt"
    repo.add_worktree("wt", str(wt), repo.branches.local["feat"])
    return main, wt


def _window_on(qtbot, tmp_path, path: Path) -> MainWindow:
    from main import _open_session

    store = JsonRepoStore(tmp_path / "repos.json")
    store.add_open(str(path))
    queries, commands = _open_session(str(path))
    win = MainWindow(
        queries, commands, store, JsonRemoteTagCache(), str(path), session_factory=_open_session
    )
    qtbot.addWidget(win)
    return win


def _log_text(win: MainWindow) -> str:
    return win._log_panel._body.toPlainText()


def _checkout_from_sidebar_menu(qtbot, win: MainWindow, branch: str) -> None:
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._sidebar.trigger_branch_action("checkout", branch)


def test_the_sidebar_menu_checkout_is_logged_after_a_repo_switch(
    qtbot, tmp_path, main_with_feat_worktree
):
    main, _wt = main_with_feat_worktree
    win = _window_on(qtbot, tmp_path, main)
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._switch_repo(str(main))

    win._sidebar.trigger_branch_action("checkout", "topic")

    assert "Checkout branch: topic" in _log_text(win)
    assert pygit2.Repository(str(main)).head.shorthand == "topic"


def test_a_branch_held_by_a_linked_worktree_opens_that_worktree(
    qtbot, tmp_path, main_with_feat_worktree
):
    main, wt = main_with_feat_worktree
    win = _window_on(qtbot, tmp_path, main)

    _checkout_from_sidebar_menu(qtbot, win, "feat")

    assert Path(win._repo_path) == wt.resolve()
    assert (main / "a.txt").read_text() == "master\n"
    assert pygit2.Repository(str(main)).head.shorthand == "master"


def test_from_a_linked_worktree_the_main_worktrees_branch_opens_main(
    qtbot, tmp_path, main_with_feat_worktree
):
    main, wt = main_with_feat_worktree
    win = _window_on(qtbot, tmp_path, wt)

    _checkout_from_sidebar_menu(qtbot, win, "master")

    assert Path(win._repo_path) == main.resolve()
    assert pygit2.Repository(str(wt)).head.shorthand == "feat"


def test_the_branches_dialog_checkout_opens_the_worktree_holding_the_branch(
    qtbot, tmp_path, main_with_feat_worktree
):
    from unittest.mock import patch

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    from git_gui.presentation.dialogs.branches_dialog import BranchesDialog

    main, wt = main_with_feat_worktree
    win = _window_on(qtbot, tmp_path, main)

    def _check_out_feat(dialog: BranchesDialog) -> int:
        table = dialog._table
        rows = range(table.rowCount())
        table.selectRow(next(r for r in rows if table.item(r, 0).data(Qt.UserRole) == "feat"))
        dialog._checkout_btn.click()
        return 0

    with (
        patch.object(BranchesDialog, "exec", _check_out_feat),
        patch.object(QMessageBox, "warning"),
        qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000),
    ):
        win._git_branches_action.trigger()

    assert Path(win._repo_path) == wt.resolve()
    assert (main / "a.txt").read_text() == "master\n"


def test_the_fixture_repo_is_on_master_whatever_the_default_branch(
    global_default_branch_main, request
):
    main, _wt = request.getfixturevalue("main_with_feat_worktree")

    repo = pygit2.Repository(str(main))

    assert not repo.head_is_unborn
    assert repo.head.shorthand == "master"
