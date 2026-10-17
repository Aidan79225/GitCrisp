"""A repo switch has to show the new repo's merge/rebase state at once.

The banners were refreshed only by the central reload, which a switch does not
run. Leaving a repo mid-merge for a clean one kept the merge banner and the
"Finish Merge" commit button, so committing in the clean repo went down the
merge-continue path with the other repo's merge message; switching into a
repo mid-merge showed no way to abort or continue it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow


def _git(cwd: Path, *args: str, check: bool = True) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=check, capture_output=True)


def _repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q", "-b", "master", ".")
    _git(path, "config", "user.name", "T")
    _git(path, "config", "user.email", "t@e.com")
    (path / "a.txt").write_text("base\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-qm", "base")
    return path


@pytest.fixture
def clean(tmp_path) -> Path:
    return _repo(tmp_path / "clean")


@pytest.fixture
def merging(tmp_path) -> Path:
    path = _repo(tmp_path / "merging")
    _git(path, "checkout", "-q", "-b", "side")
    (path / "a.txt").write_text("side\n")
    _git(path, "commit", "-qam", "side")
    _git(path, "checkout", "-q", "master")
    (path / "a.txt").write_text("master\n")
    _git(path, "commit", "-qam", "master")
    _git(path, "merge", "side", check=False)  # conflicts, leaving MERGE_HEAD
    return path


def _window(qtbot, tmp_path, path: Path) -> MainWindow:
    from main import _open_session

    queries, commands = _open_session(str(path))
    win = MainWindow(
        queries,
        commands,
        JsonRepoStore(tmp_path / "repos.json"),
        JsonRemoteTagCache(),
        str(path),
        session_factory=_open_session,
    )
    qtbot.addWidget(win)
    return win


def _switch(qtbot, win: MainWindow, path: Path) -> None:
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._switch_repo(str(path))


def _states(win: MainWindow) -> tuple[str, str]:
    return win._working_tree._current_state, win._diff._current_state


def test_switching_into_a_merge_shows_it(qtbot, tmp_path, clean, merging):
    win = _window(qtbot, tmp_path, clean)

    _switch(qtbot, win, merging)

    assert _states(win) == ("MERGING", "MERGING")


def test_leaving_a_merge_for_a_clean_repo_drops_it(qtbot, tmp_path, clean, merging):
    win = _window(qtbot, tmp_path, merging)
    assert _states(win) == ("MERGING", "MERGING")

    _switch(qtbot, win, clean)

    assert _states(win) == ("CLEAN", "CLEAN")
