"""A rebase runs in the remote-op slot, off the GUI thread.

`git rebase` replays the branch commit by commit and runs the repo's hooks, so
it takes as long as the history is long. Run on the GUI thread it froze the
window until git exited: nothing repainted, no click was handled, and the log
said nothing.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import NamedTuple
from unittest.mock import MagicMock, patch

import pytest

from git_gui.domain.entities import Branch
from git_gui.presentation.main_window import MainWindow
from tests.presentation.window_helpers import wired_window

HEAD_BEFORE = "b" * 40
HEAD_AFTER = "a" * 40
TARGET = "c" * 40

# Backstops for a git that nobody lets exit, not durations anything relies on.
_GIT_GIVES_UP_AFTER = 10.0
_WAIT_MS = 5000


class _Rebase(NamedTuple):
    """One way the user starts a rebase."""

    command: str  # the bus command that runs it
    start: Callable[[MainWindow], None]
    name: str  # what the log calls it


REBASES = {
    "onto-a-branch": _Rebase(
        "rebase",
        lambda win: win._sidebar.branch_rebase_requested.emit("feature"),
        "Rebase onto feature",
    ),
    "onto-a-commit": _Rebase(
        "rebase_onto_commit",
        lambda win: win._graph.rebase_onto_commit_requested.emit(TARGET),
        f"Rebase onto commit {TARGET[:7]}",
    ),
}


class _Git:
    """The git process behind a rebase command: it runs until the test lets it
    exit, and then moves HEAD, as a rebase does, or fails."""

    def __init__(self, head: dict[str, str]) -> None:
        self._head = head
        self._gui_thread = threading.current_thread()
        self.fails_with: Exception | None = None
        self.started = threading.Event()
        self.exit_now = threading.Event()
        self.exited = threading.Event()
        self.thread: threading.Thread | None = None

    def __call__(self, *_args) -> None:
        self.thread = threading.current_thread()
        self.started.set()
        try:
            # Only the GUI thread could let it exit, and it is what would wait
            # here: return, so that a rebase run on it fails the test, not hangs it.
            if self.thread is not self._gui_thread:
                self.exit_now.wait(_GIT_GIVES_UP_AFTER)
            if self.fails_with is not None:
                raise self.fails_with
            self._head["oid"] = HEAD_AFTER
        finally:
            self.exited.set()


@pytest.fixture(params=REBASES.values(), ids=REBASES.keys())
def rebase(request) -> _Rebase:
    return request.param


@pytest.fixture
def window(qtbot) -> Iterator[MainWindow]:
    win = wired_window(qtbot)
    log = win._log_panel
    with (
        patch.object(win, "_reload"),
        patch.object(log, "log_action", wraps=log.log_action),
        patch.object(log, "log_error", wraps=log.log_error),
    ):
        yield win


@pytest.fixture
def git(window: MainWindow) -> Iterator[_Git]:
    head = {"oid": HEAD_BEFORE}
    window._queries.get_head_oid.execute.side_effect = lambda: head["oid"]
    git = _Git(head)
    yield git
    # A test that failed before it let git exit must not leave the worker waiting.
    git.exit_now.set()


def _start_in_background(qtbot, window: MainWindow, git: _Git, rebase: _Rebase) -> None:
    """Start *rebase*, whose git keeps running until the test lets it exit: the
    window must be back before that."""
    getattr(window._commands, rebase.command).execute.side_effect = git
    rebase.start(window)
    assert not git.exited.is_set(), "the window waited for git to exit"
    qtbot.waitUntil(git.started.is_set, timeout=_WAIT_MS)


# pytest-qt closes the window before fixtures are torn down, so a worker has to
# finish inside the test, or its completion goes to a window that is gone.
def _wait_until_idle(qtbot, window: MainWindow) -> None:
    qtbot.waitUntil(lambda: not window._remote_running, timeout=_WAIT_MS)


def _let_git_exit(qtbot, window: MainWindow, git: _Git) -> None:
    git.exit_now.set()
    _wait_until_idle(qtbot, window)


def _logged(window: MainWindow) -> str:
    return window._log_panel._body.toPlainText()


def _undo_links(window: MainWindow) -> list[str]:
    """The HEAD that each Undo link in the log returns to."""
    return [call.args[2] for call in window._log_panel.log_action.call_args_list]


def test_the_window_does_not_wait_for_git(qtbot, window, git, rebase):
    _start_in_background(qtbot, window, git, rebase)

    assert git.thread is not threading.current_thread()

    _let_git_exit(qtbot, window, git)


def test_a_finished_rebase_offers_one_undo_to_where_head_was_before_it(qtbot, window, git, rebase):
    _start_in_background(qtbot, window, git, rebase)

    _let_git_exit(qtbot, window, git)

    assert _undo_links(window) == [HEAD_BEFORE]
    assert window._log_panel.log_action.call_args.args[0] == f"{rebase.name} — done"
    window._reload.assert_called_once_with()


def test_a_rebase_that_fails_is_reported_as_an_error_once_git_exits(qtbot, window, git, rebase):
    git.fails_with = RuntimeError("CONFLICT (content): Merge conflict in a.txt")
    _start_in_background(qtbot, window, git, rebase)

    _let_git_exit(qtbot, window, git)

    window._log_panel.log_error.assert_called_once_with(
        f"{rebase.name} — ERROR: CONFLICT (content): Merge conflict in a.txt"
    )
    assert window._log_panel._body.isVisibleTo(window)
    assert _undo_links(window) == []
    window._reload.assert_called_once_with()


def test_a_rebase_requested_while_a_fetch_runs_is_skipped_and_logged(qtbot, window, rebase):
    fetch_exits = threading.Event()
    window._run_remote_op("Fetch origin", lambda: fetch_exits.wait(_GIT_GIVES_UP_AFTER))
    try:
        rebase.start(window)
    finally:
        fetch_exits.set()
        _wait_until_idle(qtbot, window)

    getattr(window._commands, rebase.command).execute.assert_not_called()
    skipped = window._log_panel.log_error.call_args.args[0]
    assert rebase.name in skipped
    assert "skipped" in skipped


def test_a_fetch_requested_while_a_rebase_runs_is_skipped_and_logged(qtbot, window, git, rebase):
    _start_in_background(qtbot, window, git, rebase)

    window._on_fetch_all_prune()

    window._commands.fetch_all_prune.execute.assert_not_called()
    skipped = window._log_panel.log_error.call_args.args[0]
    assert rebase.name in skipped
    assert "skipped" in skipped

    _let_git_exit(qtbot, window, git)


@pytest.mark.parametrize(
    ("requested", "button"), [("pull_requested", "Pull"), ("push_requested", "Push")]
)
def test_a_toolbar_push_or_pull_requested_while_a_rebase_runs_is_skipped_and_logged(
    qtbot, window, git, rebase, requested, button
):
    # HEAD is detached while git replays the commits: no branch is checked out.
    window._queries.get_branches.execute.return_value = [Branch("feature", False, False, TARGET)]
    _start_in_background(qtbot, window, git, rebase)

    getattr(window._graph, requested).emit()

    logged = _logged(window)
    assert f"{button} — skipped: {rebase.name} is still running" in logged
    assert "HEAD is not on a branch" not in logged

    _let_git_exit(qtbot, window, git)


def test_a_rebase_finishing_after_a_repo_switch_offers_no_undo_in_the_new_repo(
    qtbot, window, git, rebase
):
    _start_in_background(qtbot, window, git, rebase)
    window._commands = MagicMock()  # the window lands in another repo meanwhile
    window._queries = MagicMock()

    _let_git_exit(qtbot, window, git)

    assert _undo_links(window) == []
    assert window._undoable == {}
    assert f"{rebase.name} — done" in _logged(window)


def test_a_running_rebase_shows_its_progress_but_no_cancel_button(qtbot, window, git, rebase):
    # Cancel stops a push, pull or fetch; it cannot stop a local rebase.
    window.show()

    _start_in_background(qtbot, window, git, rebase)

    assert rebase.name in window.statusBar().currentMessage()
    assert not window._cancel_remote_btn.isVisibleTo(window)

    _let_git_exit(qtbot, window, git)
