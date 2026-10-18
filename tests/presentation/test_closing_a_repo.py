"""Closing a repo moves you only if it was the one you were in, and then back
to the repo listed before it.

Closing always switched to the first open repo: closing some other row from
the repo list threw away where you were, and Ctrl+W landed on the top of the
list rather than on the previous repo the README promises.
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


@pytest.fixture
def repos(tmp_path) -> list[str]:
    """Three open repos, listed A, B, C."""
    return [_repo(tmp_path / name) for name in ("a", "b", "c")]


def _window_on(qtbot, tmp_path, repos: list[str], active: str) -> MainWindow:
    from main import _open_session

    store = JsonRepoStore(tmp_path / "repos.json")
    for path in reversed(repos):
        store.add_open(path)
    store.set_active(active)
    queries, commands = _open_session(active)
    win = MainWindow(
        queries, commands, store, JsonRemoteTagCache(), active, session_factory=_open_session
    )
    qtbot.addWidget(win)
    return win


def _close_and_wait(qtbot, win: MainWindow, path: str) -> None:
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._on_repo_close(path)


def test_closing_another_repo_leaves_you_where_you_are(qtbot, tmp_path, repos):
    a, b, c = repos
    win = _window_on(qtbot, tmp_path, repos, active=c)

    with qtbot.assertNotEmitted(win._repo_ready_signals.ready, wait=500):
        win._on_repo_close(a)

    assert win._repo_path == c
    assert win._repo_store.get_open_repos() == [b, c]
    assert win._repo_store.get_active() == c
    assert a in win._repo_store.get_recent_repos()


def test_ctrl_w_goes_back_to_the_repo_listed_before(qtbot, tmp_path, repos):
    a, b, c = repos
    win = _window_on(qtbot, tmp_path, repos, active=c)

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._close_current_repo()

    assert win._repo_path == b
    assert win._repo_store.get_open_repos() == [a, b]


def test_closing_the_first_repo_goes_to_the_next(qtbot, tmp_path, repos):
    a, b, c = repos
    win = _window_on(qtbot, tmp_path, repos, active=a)

    _close_and_wait(qtbot, win, a)

    assert win._repo_path == b
    assert win._repo_store.get_open_repos() == [b, c]


def test_closing_the_only_repo_leaves_the_window_empty(qtbot, tmp_path, repos):
    a = repos[0]
    win = _window_on(qtbot, tmp_path, [a], active=a)

    win._close_current_repo()

    assert win._repo_path is None
    assert win.windowTitle() == "GitCrisp"


def test_closing_the_only_repo_from_uncommitted_changes_shows_the_commit_pane(
    qtbot, tmp_path, repos
):
    """The working-tree pane, with its Commit and Stage buttons, has no repo
    to act on once the last one is closed."""
    a = repos[0]
    win = _window_on(qtbot, tmp_path, [a], active=a)
    win._right_stack.setCurrentWidget(win._working_tree)

    win._close_current_repo()

    assert win._right_stack.currentWidget() is win._diff


# ── Closing while another repo is still opening ──────────────────────────────


class _HeldSession:
    """A session factory that holds one repo's session until released."""

    def __init__(self, held: str) -> None:
        self.held = held
        self.release = threading.Event()

    def __call__(self, path: str):
        from main import _open_session

        if path == self.held:
            self.release.wait(5)
        return _open_session(path)


def _hold_session(win: MainWindow, path: str) -> _HeldSession:
    held = _HeldSession(path)
    win._session_factory = held
    return held


def test_closing_a_repo_that_is_still_opening_does_not_switch_to_it(qtbot, tmp_path, repos):
    a, b, _ = repos
    win = _window_on(qtbot, tmp_path, [a, b], active=a)
    held = _hold_session(win, b)
    win._switch_repo(b)

    win._on_repo_close(b)
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        held.release.set()

    assert win._repo_path == a
    assert win._repo_store.get_active() == a


def test_closing_the_last_repo_while_another_opens_lands_on_that_one(qtbot, tmp_path, repos):
    a, _, c = repos
    win = _window_on(qtbot, tmp_path, [a], active=a)
    held = _hold_session(win, c)
    win._on_repo_open(c)

    win._close_current_repo()
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        held.release.set()

    assert win._repo_path == c
    assert win._repo_store.get_open_repos() == [c]


# ── Closing the repo that owns the worktree you are in ───────────────────────


def _linked_worktree(owner: str, tmp_path: Path) -> str:
    worktree = tmp_path / "feature-wt"
    _git(Path(owner), "worktree", "add", "-q", "-b", "feature", str(worktree))
    return str(worktree.resolve())


def test_closing_the_owner_of_the_worktree_you_are_in_moves_you_on(qtbot, tmp_path, repos):
    a, b, _ = repos
    worktree = _linked_worktree(a, tmp_path)
    win = _window_on(qtbot, tmp_path, [a, b], active=a)
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._switch_repo(worktree)

    _close_and_wait(qtbot, win, a)

    assert win._repo_path == b
    assert win._repo_store.get_active() == b


def test_closing_the_repo_on_its_way_to_replace_a_closed_one_moves_on(qtbot, tmp_path, repos):
    """The repo on screen is already closed, so it is no place to stay."""
    a, b, c = repos
    win = _window_on(qtbot, tmp_path, repos, active=a)
    held = _hold_session(win, b)
    win._on_repo_close(a)  # b is on its way to replace it

    win._on_repo_close(b)
    qtbot.waitUntil(lambda: win._repo_path == c, timeout=5000)
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        held.release.set()

    assert win._repo_path == c
    assert win._repo_store.get_active() == c
