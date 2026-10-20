"""A repo that fails to open must not change what the store says is open.

Opening wrote the path into the open list, made it active and saved — all
before the session was tried — and a failure only logged. A deleted folder
under Recent therefore became the active, open repo on disk while the window
went on showing the previous one. Closing had the mirror-image problem: when
the next repo could not open, the closed one stayed on screen, so Ctrl+W
retried the broken repo forever and the empty state was unreachable.
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


def _repo(path: Path) -> str:
    path.mkdir()
    _git(path, "init", "-q", "-b", "master", ".")
    _git(path, "config", "user.name", "T")
    _git(path, "config", "user.email", "t@e.com")
    (path / "a.txt").write_text("x\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-qm", "init")
    return str(path)


@pytest.fixture
def current(tmp_path) -> str:
    return _repo(tmp_path / "current")


@pytest.fixture
def gone(tmp_path) -> str:
    return str(tmp_path / "deleted-since")


@pytest.fixture
def store(tmp_path, current) -> JsonRepoStore:
    s = JsonRepoStore(tmp_path / "repos.json")
    s.add_open(current)
    return s


@pytest.fixture
def window(qtbot, store, current):
    from main import _open_session

    queries, commands = _open_session(current)
    w = MainWindow(
        queries, commands, store, JsonRemoteTagCache(), current, session_factory=_open_session
    )
    qtbot.addWidget(w)
    return w


def test_a_recent_repo_that_fails_to_open_stays_recent(qtbot, window, store, current, gone):
    store.add_open(gone)
    store.close_repo(gone)
    store.set_active(current)

    with qtbot.waitSignal(window._repo_ready_signals.failed, timeout=5000):
        window._on_repo_open(gone)

    assert window._repo_path == current
    assert store.get_open_repos() == [current]
    assert store.get_active() == current
    assert gone in store.get_recent_repos()


def test_a_recent_repo_that_opens_joins_the_open_list(qtbot, tmp_path, window, store, current):
    other = _repo(tmp_path / "other")

    with qtbot.waitSignal(window._repo_ready_signals.ready, timeout=5000):
        window._on_repo_open(other)

    assert window._repo_path == other
    assert store.get_open_repos() == [other, current]
    assert store.get_active() == other


def test_closing_onto_a_repo_that_fails_ends_empty(qtbot, window, store, current, gone):
    store.add_open(gone)
    store.set_open_order([current, gone])
    store.set_active(current)

    with qtbot.waitSignal(window._repo_ready_signals.failed, timeout=5000):
        window._close_current_repo()

    assert window._repo_path is None
    assert window.windowTitle() == "GitCrisp"
    assert store.get_open_repos() == [gone]
    assert current in store.get_recent_repos()
