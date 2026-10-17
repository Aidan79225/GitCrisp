"""A finished clone and an opened submodule join the repo list only once open.

Both wrote the path into the store as open and active, and saved, before the
session was tried. A clone or submodule that then failed to open stayed
listed as the active repo on disk while the window went on showing the
previous one.
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
def first(tmp_path) -> str:
    return _repo(tmp_path / "first")


@pytest.fixture
def current(tmp_path) -> str:
    return _repo(tmp_path / "current")


@pytest.fixture
def store(tmp_path, first, current) -> JsonRepoStore:
    s = JsonRepoStore(tmp_path / "repos.json")
    s.add_open(first)
    s.add_open(current, after=first)
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


def _broken_submodule(parent: str) -> str:
    """A submodule whose .git file points at a gitdir that is not there."""
    sub = Path(parent) / "lib"
    sub.mkdir()
    (sub / ".git").write_text("gitdir: ../.git/modules/missing\n", encoding="utf-8")
    return str(sub)


def test_a_clone_that_fails_to_open_is_not_listed_as_open(qtbot, tmp_path, window, store, current):
    gone = str(tmp_path / "clone-removed-since")

    with qtbot.waitSignal(window._repo_ready_signals.failed, timeout=5000):
        window._on_clone_completed(gone)

    assert window._repo_path == current
    assert gone not in store.get_open_repos()
    assert store.get_active() == current


def test_a_clone_that_opens_becomes_the_active_repo(qtbot, tmp_path, window, store):
    clone = _repo(tmp_path / "clone")

    with qtbot.waitSignal(window._repo_ready_signals.ready, timeout=5000):
        window._on_clone_completed(clone)

    assert window._repo_path == clone
    assert clone in store.get_open_repos()
    assert store.get_active() == clone


def test_a_submodule_that_fails_to_open_is_not_listed_as_open(qtbot, window, store, current):
    sub = _broken_submodule(current)

    with qtbot.waitSignal(window._repo_ready_signals.failed, timeout=5000):
        window._on_submodule_open_requested(sub)

    assert window._repo_path == current
    assert sub not in store.get_open_repos()
    assert store.get_active() == current


def test_a_submodule_that_opens_is_listed_right_after_its_parent(
    qtbot, window, store, first, current
):
    sub = _repo(Path(current) / "lib")

    with qtbot.waitSignal(window._repo_ready_signals.ready, timeout=5000):
        window._on_submodule_open_requested(sub)

    assert window._repo_path == sub
    assert store.get_open_repos() == [first, current, sub]
    assert store.get_active() == sub
