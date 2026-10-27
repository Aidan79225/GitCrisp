"""Closing the repo whose linked worktree you are in leaves nothing to relaunch onto.

Switching to a linked worktree makes it the stored active repo without adding
it to the open list. Closing its owner closed what was on screen, but the
store went on naming the worktree as active, so when nothing took its place
the next launch opened straight onto a worktree whose repo was closed, with
no row for it anywhere in the list.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _repo(path: Path) -> str:
    path.mkdir()
    _git(path, "init", "-q", "-b", "master", ".")
    _git(path, "config", "user.name", "T")
    _git(path, "config", "user.email", "t@e.com")
    (path / "a.txt").write_text("x\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-qm", "init")
    return str(path)


def _linked_worktree(owner: str, tmp_path: Path) -> str:
    worktree = tmp_path / "feature-wt"
    _git(Path(owner), "worktree", "add", "-q", "-b", "feature", str(worktree))
    return str(worktree.resolve())


def _in_worktree_of(qtbot, tmp_path: Path, open_repos: list[str]) -> tuple[MainWindow, str]:
    """A window on the first open repo's linked worktree, switched to in-session."""
    from main import _open_session

    owner = open_repos[0]
    worktree = _linked_worktree(owner, tmp_path)
    store = JsonRepoStore(tmp_path / "repos.json")
    for path in reversed(open_repos):
        store.add_open(path)
    queries, commands = _open_session(owner)
    win = MainWindow(
        queries, commands, store, JsonRemoteTagCache(), owner, session_factory=_open_session
    )
    qtbot.addWidget(win)
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._switch_repo(worktree)
    return win, worktree


def _relaunch_candidates(tmp_path: Path) -> list[str]:
    from main import _startup_candidates

    store = JsonRepoStore(tmp_path / "repos.json")
    store.load()
    return _startup_candidates(store)


def test_closing_the_only_repo_from_its_worktree_leaves_nothing_active(qtbot, tmp_path):
    a = _repo(tmp_path / "a")
    win, _ = _in_worktree_of(qtbot, tmp_path, [a])

    win._on_repo_close(a)

    assert win._repo_path is None
    assert win._repo_store.get_active() is None
    assert _relaunch_candidates(tmp_path) == []


def test_a_successor_that_fails_to_open_leaves_nothing_active(qtbot, tmp_path):
    from main import _open_session

    a, b = _repo(tmp_path / "a"), _repo(tmp_path / "b")
    win, _ = _in_worktree_of(qtbot, tmp_path, [a, b])

    def _b_fails(path: str):
        if path == b:
            raise RuntimeError("share went away")
        return _open_session(path)

    win._session_factory = _b_fails
    with qtbot.waitSignal(win._repo_ready_signals.failed, timeout=5000):
        win._on_repo_close(a)

    assert win._repo_path is None
    assert win._repo_store.get_active() is None
    assert _relaunch_candidates(tmp_path) == [b]
