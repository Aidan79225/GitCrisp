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
        self.calls: list[str] = []

    def __call__(self, path: str):
        from main import _open_session

        self.calls.append(path)
        if path == self.failing:
            self.release.wait(5)
            raise RuntimeError("share went away")
        return _open_session(path)


@pytest.fixture
def repos(tmp_path) -> list[str]:
    """Three open repos, listed C, A, B."""
    return [_repo(tmp_path / name) for name in ("c", "a", "b")]


def _window(
    qtbot, tmp_path, open_repos: list[str], on_screen: str, failing: str
) -> tuple[MainWindow, _FailingLater]:
    """A window on *on_screen* with *open_repos* listed in that order."""
    from main import _open_session

    store = JsonRepoStore(tmp_path / "repos.json")
    for path in reversed(open_repos):
        store.add_open(path)
    store.set_active(on_screen)
    queries, commands = _open_session(on_screen)
    factory = _FailingLater(failing)
    win = MainWindow(
        queries, commands, store, JsonRemoteTagCache(), on_screen, session_factory=factory
    )
    qtbot.addWidget(win)
    return win, factory


def _window_on_a(
    qtbot, tmp_path, repos: list[str], failing: str | None = None
) -> tuple[MainWindow, _FailingLater]:
    """A window on A whose session factory fails *failing*, B by default."""
    c, a, b = repos
    return _window(qtbot, tmp_path, repos, a, failing or b)


def _log_text(win: MainWindow) -> str:
    return win._log_panel._body.toPlainText()


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


def test_closing_the_repo_ctrl_w_handed_over_to_lands_on_the_previous_repo(qtbot, tmp_path, repos):
    """It was about to fill the empty window: closing it goes where closing it
    on screen would."""
    c, a, b = repos
    win, factory = _window_on_a(qtbot, tmp_path, repos)
    win._switch_repo(b)
    win._close_current_repo()

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._on_repo_close(b)
    with qtbot.waitSignal(win._repo_ready_signals.failed, timeout=5000):
        factory.release.set()

    assert win._repo_path == c
    assert win._repo_store.get_open_repos() == [c]


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


def test_a_failing_repo_ctrl_w_handed_over_to_is_opened_once(qtbot, tmp_path):
    """The previous repo is the one on its way: failing is no reason to retry it."""
    b, a = _repo(tmp_path / "b"), _repo(tmp_path / "a")
    win, factory = _window(qtbot, tmp_path, [b, a], on_screen=a, failing=b)
    win._switch_repo(b)
    win._close_current_repo()

    factory.release.set()
    # Nothing is on its way once the window has given up: a retry is asked
    # for before the first failure's slot returns.
    qtbot.waitUntil(lambda: win._repo_request is None, timeout=5000)

    assert factory.calls == [b]
    assert _log_text(win).count("Cannot open") == 1
    assert win._repo_path is None
    assert win._repo_store.get_open_repos() == [b]


def test_a_failing_repo_ctrl_w_handed_over_to_falls_back_past_itself(qtbot, tmp_path):
    b, a, d = (_repo(tmp_path / name) for name in ("b", "a", "d"))
    win, factory = _window(qtbot, tmp_path, [b, a, d], on_screen=a, failing=b)
    win._switch_repo(b)
    win._close_current_repo()

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        factory.release.set()

    assert win._repo_path == d
    assert factory.calls == [b, d]


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
