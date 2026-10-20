"""An open reflog pane has to follow HEAD, like everything else on screen.

The central reload refreshed the sidebar, the commit list and the working
tree, but not the reflog. The sidebar stays visible beside it, so a checkout
from there — or a commit made in a terminal — left the pane without the newest
movement, every HEAD@{n} off by one, and the restore action naming a branch
that was no longer the one a reset would move.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path) -> Path:
    path = tmp_path / "r"
    path.mkdir()
    _git(path, "init", "-q", "-b", "master", ".")
    _git(path, "config", "user.name", "T")
    _git(path, "config", "user.email", "t@e.com")
    (path / "a.txt").write_text("x\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-qm", "init")
    _git(path, "branch", "feature")
    return path


@pytest.fixture
def window(qtbot, tmp_path, repo):
    from main import _open_session

    queries, commands = _open_session(str(repo))
    w = MainWindow(
        queries,
        commands,
        JsonRepoStore(tmp_path / "repos.json"),
        JsonRemoteTagCache(),
        str(repo),
        session_factory=_open_session,
    )
    qtbot.addWidget(w)
    return w


def _open_reflog(qtbot, window):
    window.open_reflog()
    pane = window._reflog_pane
    qtbot.waitUntil(lambda: pane.restore_target() == "master", timeout=5000)
    return pane


def test_a_reload_shows_the_newest_movement(qtbot, window, repo):
    pane = _open_reflog(qtbot, window)
    before = pane._model.rowCount()

    (repo / "a.txt").write_text("changed in a terminal\n")
    _git(repo, "commit", "-qam", "outside the app")
    window._reload()

    qtbot.waitUntil(lambda: pane._model.rowCount() == before + 1, timeout=5000)


def test_a_reload_names_the_branch_a_restore_would_now_move(qtbot, window, repo):
    pane = _open_reflog(qtbot, window)

    _git(repo, "checkout", "-q", "feature")
    window._reload()

    qtbot.waitUntil(lambda: pane.restore_target() == "feature", timeout=5000)
