"""A window that opens on a linked worktree shows it under the repo it belongs to.

Switching to a worktree makes it active without adding it to the open list,
so a relaunch opens straight onto it. Its group was only ever loaded for an
active path that is itself an open repo: the relaunched window showed the
owning repo un-highlighted, with no row for the worktree you were in.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow
from git_gui.presentation.widgets.repo_list import _IS_ACTIVE_ROLE


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _repo_with_worktree(tmp_path: Path) -> tuple[str, str]:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "master", ".")
    _git(main, "config", "user.name", "T")
    _git(main, "config", "user.email", "t@e.com")
    (main / "a.txt").write_text("x\n")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-qm", "init")
    worktree = tmp_path / "feature-wt"
    _git(main, "worktree", "add", "-q", "-b", "feature", str(worktree))
    return str(main), str(worktree.resolve())


def _relaunch_on(qtbot, tmp_path: Path, open_repo: str, active: str) -> MainWindow:
    from main import _open_session

    store = JsonRepoStore(tmp_path / "repos.json")
    store.add_open(open_repo)
    store.set_active(active)
    queries, commands = _open_session(active)
    win = MainWindow(
        queries, commands, store, JsonRemoteTagCache(), active, session_factory=_open_session
    )
    qtbot.addWidget(win)
    return win


def _worktree_rows_under(win: MainWindow, owner: str) -> dict[str, bool]:
    """Path -> is-active for each worktree row under *owner*'s open row."""
    model = win._repo_list._model
    open_header = model.item(0)
    for row in range(open_header.rowCount()):
        repo_item = open_header.child(row)
        if repo_item.data(Qt.UserRole) == owner:
            children = (repo_item.child(i) for i in range(repo_item.rowCount()))
            return {c.data(Qt.UserRole): bool(c.data(_IS_ACTIVE_ROLE)) for c in children}
    return {}


def test_relaunching_on_a_worktree_shows_it_active_under_its_repo(qtbot, tmp_path):
    main, worktree = _repo_with_worktree(tmp_path)

    win = _relaunch_on(qtbot, tmp_path, open_repo=main, active=worktree)

    assert _worktree_rows_under(win, main) == {worktree: True}


def test_relaunching_on_a_worktree_knows_where_its_branches_are_checked_out(qtbot, tmp_path):
    main, worktree = _repo_with_worktree(tmp_path)

    win = _relaunch_on(qtbot, tmp_path, open_repo=main, active=worktree)

    assert win._worktree_paths_by_branch == {"feature": worktree}
