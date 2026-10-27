"""A second attempt at the same repo is answered by its own open, not by the first's.

Clicking a slow row again, or holding Ctrl+<n> (the shortcut repeats), opens
the same path twice on two threads. The answers were matched to the request
by path alone, so the first attempt's late failure was taken for the second
attempt's: the window gave up on a repo that was about to open, or, once it
had opened, left it for the fallback of a close handed over to it.
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


class _WakingShare:
    """Opens sessions for real, but holds each attempt at *slow* until its
    gate opens; the first attempt then fails, as a share waking up times out."""

    def __init__(self, slow: str) -> None:
        from main import _open_session

        self._open = _open_session
        self._slow = slow
        self.gates = [threading.Event(), threading.Event()]
        self.started = 0
        self._count = threading.Lock()

    def __call__(self, path: str):
        if path != self._slow:
            return self._open(path)
        with self._count:
            attempt = self.started
            self.started += 1
        self.gates[attempt].wait(timeout=10)
        if attempt == 0:
            raise OSError("the network name is no longer available")
        return self._open(path)


@pytest.fixture
def repos(tmp_path) -> dict[str, str]:
    return {name: _repo(tmp_path / name) for name in ("a", "b", "c")}


@pytest.fixture
def share(repos):
    share = _WakingShare(repos["b"])
    yield share
    for gate in share.gates:
        gate.set()


def _window_on_a(qtbot, tmp_path, repos, share, open_repos: list[str]) -> MainWindow:
    store = JsonRepoStore(tmp_path / "repos.json")
    for name in reversed(open_repos):
        store.add_open(repos[name])
    queries, commands = share(repos["a"])
    win = MainWindow(
        queries, commands, store, JsonRemoteTagCache(), repos["a"], session_factory=share
    )
    qtbot.addWidget(win)
    return win


def _ask_twice_for_b(qtbot, win: MainWindow, repos, share) -> None:
    for attempt in (1, 2):
        win._switch_repo(repos["b"])
        qtbot.waitUntil(lambda attempt=attempt: share.started == attempt, timeout=5000)


def test_a_first_attempt_failing_late_does_not_cancel_the_second(qtbot, tmp_path, repos, share):
    win = _window_on_a(qtbot, tmp_path, repos, share, ["a", "b"])
    _ask_twice_for_b(qtbot, win, repos, share)

    with qtbot.waitSignal(win._repo_ready_signals.failed, timeout=5000):
        share.gates[0].set()
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        share.gates[1].set()

    assert win._repo_path == repos["b"]
    assert win._repo_store.get_active() == repos["b"]


def test_a_first_attempt_failing_after_the_second_landed_keeps_the_window_there(
    qtbot, tmp_path, repos, share
):
    """Ctrl+W on A hands over to B, with C to fall back on if B fails."""
    win = _window_on_a(qtbot, tmp_path, repos, share, ["c", "a", "b"])
    _ask_twice_for_b(qtbot, win, repos, share)
    win._close_current_repo()

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        share.gates[1].set()
    assert win._repo_path == repos["b"]
    with qtbot.waitSignal(win._repo_ready_signals.failed, timeout=5000):
        share.gates[0].set()

    assert win._pending_request() is None, "nothing is to replace the repo that opened"
    assert win._repo_path == repos["b"]
