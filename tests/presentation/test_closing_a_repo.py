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
from PySide6.QtCore import Qt

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


# ── Ctrl+W inside a linked worktree ──────────────────────────────────────────


def _in_worktree_of(qtbot, tmp_path, open_repos: list[str], owner: str) -> tuple[MainWindow, str]:
    """A window on *owner*'s linked worktree, switched to in-session.

    The worktree gets no row of its own: it hangs under *owner*'s.
    """
    worktree = _linked_worktree(owner, tmp_path)
    win = _window_on(qtbot, tmp_path, open_repos, active=owner)
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._switch_repo(worktree)
    return win, worktree


def _worktrees_listed_under(win: MainWindow, owner: str) -> list[str]:
    open_header = win._repo_list._model.item(0)
    for row in range(open_header.rowCount()):
        repo_item = open_header.child(row)
        if repo_item.data(Qt.UserRole) == owner:
            return [repo_item.child(i).data(Qt.UserRole) for i in range(repo_item.rowCount())]
    return []


def _settled(qtbot, win: MainWindow) -> None:
    """Let the loads under way finish: a worker must not outlive its test."""
    win._stop_change_detector()
    qtbot.waitUntil(lambda: not win._graph._loading, timeout=10000)


@pytest.mark.parametrize(
    ("open_names", "owner_name"),
    [
        pytest.param("abc", "a", id="owner first"),
        pytest.param("abc", "b", id="owner in the middle"),
        pytest.param("abc", "c", id="owner last"),
        pytest.param("c", "c", id="owner only"),
    ],
)
def test_ctrl_w_in_a_linked_worktree_goes_back_to_its_owner(
    qtbot, tmp_path, repos, open_names, owner_name
):
    """The worktree has no row to close, only the owner's. It went to the first
    open repo whoever owned it, closed nothing, and listed the worktree as a
    closed repo under RECENT."""
    paths = dict(zip("abc", repos))
    open_repos = [paths[name] for name in open_names]
    owner = paths[owner_name]
    win, worktree = _in_worktree_of(qtbot, tmp_path, open_repos, owner)
    recent_before = win._repo_store.get_recent_repos()

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._close_current_repo()

    assert win._repo_path == owner
    assert win._repo_store.get_active() == owner
    assert win._repo_store.get_open_repos() == open_repos
    assert win._repo_store.get_recent_repos() == recent_before
    assert _worktrees_listed_under(win, owner) == [worktree]


def test_ctrl_w_in_a_linked_worktree_whose_owner_is_not_open_closes_it_as_before(
    qtbot, tmp_path, repos
):
    """Relaunched onto a worktree whose repo is closed: no owner to go back to."""
    a, b, c = repos
    worktree = _linked_worktree(c, tmp_path)
    win = _window_on(qtbot, tmp_path, [a, b], active=worktree)

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._close_current_repo()

    assert win._repo_path == a
    assert win._repo_store.get_open_repos() == [a, b]
    assert win._repo_store.get_recent_repos() == [worktree]


def test_ctrl_w_in_a_linked_worktree_while_another_repo_opens_hands_over_to_it(
    qtbot, tmp_path, repos
):
    """The repo the user already asked for takes over; going back to the owner
    would have replaced that request, and closing the worktree, which has no
    row to close, listed it under RECENT."""
    a, _, c = repos
    win, _ = _in_worktree_of(qtbot, tmp_path, repos, owner=c)
    recent_before = win._repo_store.get_recent_repos()
    held = _hold_session(win, a)
    win._switch_repo(a)

    win._close_current_repo()
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        held.release.set()

    assert win._repo_path == a
    assert win._repo_store.get_open_repos() == repos
    assert win._repo_store.get_recent_repos() == recent_before


def test_a_second_ctrl_w_while_the_first_is_still_opening_the_owner_does_nothing(
    qtbot, tmp_path, repos
):
    """The first press asks for the owner. The second found that request
    pending and closed the worktree instead: it was listed under RECENT, and
    the window went blank until the owner opened. A held key repeats."""
    _, _, c = repos
    win, worktree = _in_worktree_of(qtbot, tmp_path, repos, owner=c)
    recent_before = win._repo_store.get_recent_repos()
    held = _hold_session(win, c)

    win._close_current_repo()
    win._close_current_repo()

    assert win._repo_path == worktree, "the worktree stays up until the owner opens"
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        held.release.set()
    assert win._repo_path == c
    assert win._repo_store.get_open_repos() == repos
    assert win._repo_store.get_recent_repos() == recent_before
    assert _worktrees_listed_under(win, c) == [worktree]
    _settled(qtbot, win)


def test_ctrl_w_after_closing_the_owner_while_its_replacement_opens_does_nothing(
    qtbot, tmp_path, repos
):
    """The owner's row went and took the worktree's with it, and b is on its
    way to replace the screen. Ctrl+W then closed the worktree as a repo of its
    own: it was listed under RECENT, and the window went blank until b opened."""
    a, b, c = repos
    win, worktree = _in_worktree_of(qtbot, tmp_path, repos, owner=c)
    held = _hold_session(win, b)
    win._on_repo_close(c)  # b is on its way to replace it
    recent_before = win._repo_store.get_recent_repos()

    win._close_current_repo()

    assert win._repo_path == worktree, "the worktree stays up until b opens"
    assert win._repo_store.get_recent_repos() == recent_before
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        held.release.set()
    assert win._repo_path == b
    assert win._repo_store.get_open_repos() == [a, b]
    assert win._repo_store.get_recent_repos() == recent_before
    _settled(qtbot, win)


def test_closing_the_owner_again_while_its_replacement_opens_leaves_the_screen_alone(
    qtbot, tmp_path, repos
):
    """The owner's row stays drawn until b has opened, so it can be closed
    again. The owner is closed already: the second close leaves the worktree up
    for b to replace rather than blanking the window."""
    a, b, c = repos
    win, worktree = _in_worktree_of(qtbot, tmp_path, repos, owner=c)
    held = _hold_session(win, b)
    win._on_repo_close(c)  # b is on its way to replace it
    win._on_repo_close(c)  # the same row, closed again

    assert win._repo_path == worktree, "the worktree stays up until b opens"
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        held.release.set()
    assert win._repo_path == b
    assert win._repo_store.get_open_repos() == [a, b]
    _settled(qtbot, win)


# ── Closing the repo on screen again while its replacement opens ─────────────


def test_closing_the_closed_repo_again_while_its_replacement_opens_leaves_the_screen_alone(
    qtbot, tmp_path, repos
):
    """c's row stays drawn until b has opened, so it can be closed again. c is
    closed already: the second close left the window blank until b opened."""
    a, b, c = repos
    win = _window_on(qtbot, tmp_path, repos, active=c)
    held = _hold_session(win, b)
    win._on_repo_close(c)  # b is on its way to replace it
    win._on_repo_close(c)  # the same row, closed again

    assert win._repo_path == c, "c stays up until b opens"
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        held.release.set()
    assert win._repo_path == b
    assert win._repo_store.get_open_repos() == [a, b]
    _settled(qtbot, win)
