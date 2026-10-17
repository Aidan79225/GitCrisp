"""The repo on screen is the one the user asked for last, not the slowest to open.

Each switch opens its session on its own thread, and every result used to be
applied as it arrived. Clicking a repo on a slow network share and then a
local one showed the local one, then jumped back to the slow one when it
finally opened — and saved it as the active repo.
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


class _SlowShare:
    """Opens sessions for real, but holds one path until released."""

    def __init__(self, slow_path: str) -> None:
        from main import _open_session

        self._open = _open_session
        self._slow_path = slow_path
        self.release = threading.Event()

    def __call__(self, path: str):
        if path == self._slow_path:
            self.release.wait(timeout=10)
        return self._open(path)


@pytest.fixture
def repos(tmp_path) -> dict[str, str]:
    return {name: _repo(tmp_path / name) for name in ("a", "slow", "c")}


@pytest.fixture
def share(repos) -> _SlowShare:
    return _SlowShare(repos["slow"])


@pytest.fixture
def window(qtbot, tmp_path, repos, share):
    queries, commands = share(repos["a"])
    store = JsonRepoStore(tmp_path / "repos.json")
    for name in ("c", "slow", "a"):
        store.add_open(repos[name])
    w = MainWindow(
        queries, commands, store, JsonRemoteTagCache(), repos["a"], session_factory=share
    )
    qtbot.addWidget(w)
    yield w
    share.release.set()


def _let_the_slow_open_finish(qtbot, window, share) -> None:
    with qtbot.waitSignal(window._repo_ready_signals.ready, timeout=5000):
        share.release.set()


def test_a_slow_open_does_not_override_a_later_choice(qtbot, window, repos, share):
    window._switch_repo(repos["slow"])
    with qtbot.waitSignal(window._repo_ready_signals.ready, timeout=5000):
        window._switch_repo(repos["c"])
    assert window._repo_path == repos["c"]

    _let_the_slow_open_finish(qtbot, window, share)

    assert window._repo_path == repos["c"]
    assert window.windowTitle() == f"GitCrisp — {repos['c']}"
    assert window._repo_store.get_active() == repos["c"]


def test_a_slow_open_does_not_reopen_a_window_left_empty(qtbot, window, repos, share):
    window._switch_repo(repos["slow"])
    window._enter_empty_state()

    _let_the_slow_open_finish(qtbot, window, share)

    assert window._repo_path is None
    assert window.windowTitle() == "GitCrisp"
