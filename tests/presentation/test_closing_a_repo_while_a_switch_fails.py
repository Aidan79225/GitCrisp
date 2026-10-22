"""Ctrl+W lands on the previous repo when the switch it waited for fails.

Closing the repo on screen while a switch to another was still loading leaves
that switch to take over. When it then failed, nothing did: the window stayed
empty with other repos still open, and Ctrl+W did nothing more, where the
README promises it switches to the previous repo.
"""

from __future__ import annotations

import subprocess
import threading
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


class _FailingLater:
    """Opens every repo but one, which fails once released."""

    def __init__(self, failing: str) -> None:
        self.failing = failing
        self.release = threading.Event()

    def __call__(self, path: str):
        from main import _open_session

        if path == self.failing:
            self.release.wait(5)
            raise RuntimeError("share went away")
        return _open_session(path)


@pytest.fixture
def repos(tmp_path) -> list[str]:
    """Three open repos, listed C, A, B."""
    return [_repo(tmp_path / name) for name in ("c", "a", "b")]


def _window_on_a(
    qtbot, tmp_path, repos: list[str], failing: str | None = None
) -> tuple[MainWindow, _FailingLater]:
    """A window on A whose session factory fails *failing*, B by default."""
    from main import _open_session

    c, a, b = repos
    store = JsonRepoStore(tmp_path / "repos.json")
    for path in reversed(repos):
        store.add_open(path)
    store.set_active(a)
    queries, commands = _open_session(a)
    factory = _FailingLater(failing or b)
    win = MainWindow(queries, commands, store, JsonRemoteTagCache(), a, session_factory=factory)
    qtbot.addWidget(win)
    return win, factory


def test_ctrl_w_during_a_switch_that_fails_lands_on_the_previous_repo(qtbot, tmp_path, repos):
    c, a, b = repos
    win, factory = _window_on_a(qtbot, tmp_path, repos)
    win._switch_repo(b)

    win._close_current_repo()
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        factory.release.set()

    assert win._repo_path == c
    assert win._repo_store.get_active() == c
    assert win._repo_store.get_open_repos() == [c, b]


def test_a_previous_repo_closed_meanwhile_is_not_reopened(qtbot, tmp_path, repos):
    c, a, b = repos
    win, factory = _window_on_a(qtbot, tmp_path, repos)
    win._switch_repo(b)
    win._close_current_repo()
    win._on_repo_close(c)

    with qtbot.waitSignal(win._repo_ready_signals.failed, timeout=5000):
        factory.release.set()
    qtbot.wait(300)

    assert win._repo_path is None
    assert win._repo_store.get_active() is None
    assert win._repo_store.get_open_repos() == [b]


def test_ctrl_w_after_a_switch_has_failed_lands_on_the_previous_repo(qtbot, tmp_path, repos):
    c, a, b = repos
    win, factory = _window_on_a(qtbot, tmp_path, repos)
    factory.release.set()
    with qtbot.waitSignal(win._repo_ready_signals.failed, timeout=5000):
        win._switch_repo(b)
    assert win._repo_path == a  # a failed switch leaves the window where it was

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._close_current_repo()

    assert win._repo_path == c
    assert win._repo_store.get_open_repos() == [c, b]


def test_ctrl_w_after_an_open_has_failed_lands_on_the_previous_repo(qtbot, tmp_path, repos):
    c, a, b = repos
    recent = _repo(tmp_path / "recent")
    win, factory = _window_on_a(qtbot, tmp_path, repos, failing=recent)
    factory.release.set()
    with qtbot.waitSignal(win._repo_ready_signals.failed, timeout=5000):
        win._on_repo_open(recent)

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._close_current_repo()

    assert win._repo_path == c
    assert win._repo_store.get_open_repos() == [c, b]
