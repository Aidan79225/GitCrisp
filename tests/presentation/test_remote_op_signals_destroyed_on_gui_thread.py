"""A remote op's signals are deleted by Qt on the GUI thread, never by a worker.

_run_remote_op hands its worker a signals object to answer through. Parentless, the
window's reference to it was rebound by the next op, which left a worker still
unwinding from its answer the last to let go of the previous op's; and a closed window's
wrapper, kept alive by a reference cycle (the repo list's lambda names the window), held
the newest op's until the garbage collector reached it, on whichever thread ran it.
They belong to the application now (worker_signals) and go when their worker has
returned, so a window closed under a running op leaves them alive with nobody listening.
"""

from __future__ import annotations

import gc
import itertools
import threading
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
import shiboken6
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.ports import RemoteOperationCancelled
from git_gui.presentation.main_window import MainWindow, remote_op_queue
from git_gui.presentation.widgets.background import start_daemon_thread
from tests.presentation.thread_helpers import Gate, deliver_queued_answers, recording
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit
from tests.presentation.window_helpers import blank_window

# How git ends an op: it succeeds, fails or is cancelled, and the worker answers
# through a signal of its own for each.
GIT_ENDS = [
    pytest.param(None, id="done"),
    pytest.param(RuntimeError, id="failed"),
    pytest.param(RemoteOperationCancelled, id="cancelled"),
]

REJECTED_PUSH = "! [rejected] feature -> feature (non-fast-forward)"


@pytest.fixture
def destroyed_on(monkeypatch) -> list[str]:
    """The name of the thread that destroyed each op's signals, as they are destroyed."""
    names: list[str] = []
    monkeypatch.setattr(
        remote_op_queue, "_RemoteSignals", recording(remote_op_queue._RemoteSignals, names)
    )
    return names


def _window(qtbot, **window_kwargs) -> MainWindow:
    win = blank_window(qtbot, **window_kwargs)
    win._commands = MagicMock()
    return win


def _wait_until_idle(qtbot, win: MainWindow) -> None:
    qtbot.waitUntil(lambda: not win._remote_running, timeout=5000)


def _git(ends_with: type[Exception] | None, *, held_by: Gate | None = None) -> Callable[[], None]:
    """What an op runs: git, which waits for *held_by* if given, then ends in *ends_with*."""

    def run() -> None:
        if held_by is not None:
            held_by.hold()
        if ends_with is not None:
            raise ends_with("git ended it")

    return run


class _FirstWorkerLingers:
    """A runner whose first worker, once it has answered, waits before its thread ends.

    That is a worker still unwinding from its answer, with everything its closure holds
    still in its hands. Every later worker runs and ends as usual.
    """

    def __init__(self) -> None:
        self.gate = Gate()
        self._workers = itertools.count()

    def __call__(self, work: Callable[[], None]) -> None:
        lingers = next(self._workers) == 0

        def run() -> None:
            work()
            if lingers:
                self.gate.hold()

        start_daemon_thread(run)


@pytest.mark.parametrize("git_ends_with", GIT_ENDS)
def test_an_ops_signals_are_destroyed_on_the_gui_thread_when_its_worker_outlives_the_op(
    qtbot, destroyed_on, git_ends_with
):
    gui_thread = threading.current_thread().name
    lingering = _FirstWorkerLingers()
    with workers_joined_on_exit():
        win = _window(qtbot, remote_op_runner=lingering)
        try:
            win._run_remote_op("Fetch origin", _git(git_ends_with))
            first_worker = lingering.gate.held_worker()  # answered, and still unwinding
            _wait_until_idle(qtbot, win)  # the window has taken the answer
            win._run_remote_op("Fetch upstream", _git(None))  # the slot is free: the next op starts
            _wait_until_idle(qtbot, win)
        finally:
            lingering.gate.open()
        first_worker.join(5)
        assert not first_worker.is_alive()
    deliver_queued_answers()

    assert [name for name in destroyed_on if name != gui_thread] == []
    assert len(destroyed_on) == 2  # one per op: the first one's did not outlive its worker


@pytest.mark.parametrize("git_ends_with", GIT_ENDS)
def test_a_closed_windows_signals_outlive_it_until_the_worker_has_returned(
    qtbot, destroyed_on, worker_errors, git_ends_with
):
    gui_thread = threading.current_thread().name
    git = Gate()
    with workers_joined_on_exit():
        win = _window(qtbot)
        win._run_remote_op("Fetch origin", _git(git_ends_with, held_by=git))
        try:
            worker = git.held_worker()
            shiboken6.delete(win)  # closed with the op still in git
            # qtbot holds the window by a weak reference and closes it at teardown, which
            # raises for a deleted window: its wrapper, kept alive by a cycle, goes first.
            del win
            gc.collect()
            deliver_queued_answers()
            # Deleted with the window, they would be gone under a worker about to emit.
            assert destroyed_on == []
        finally:
            git.open()
        worker.join(5)
        assert not worker.is_alive()
    deliver_queued_answers()

    assert destroyed_on == [gui_thread]
    assert worker_errors == []


def test_a_rejected_pushs_signals_are_deleted_while_its_force_push_offer_is_open(
    qtbot, destroyed_on
):
    """The offer is a modal box: an event loop inside the failure's own slot.

    The worker asks for the deletion as it returns, from its own thread, so any
    running event loop may carry it out, the box's included. The slot must carry on
    and start the force push after the signals it was called from are gone.
    """
    gui_thread = threading.current_thread().name
    gone_during_the_offer: list[str] = []

    def the_offer_is_open(*_args) -> int:
        qtbot.waitUntil(lambda: bool(destroyed_on), timeout=5000)  # the box's event loop
        gone_during_the_offer.extend(destroyed_on)
        return QMessageBox.Yes

    with workers_joined_on_exit():
        win = _window(qtbot)
        win._commands.push.execute.side_effect = RuntimeError(REJECTED_PUSH)
        with patch.object(remote_op_queue.QMessageBox, "warning", side_effect=the_offer_is_open):
            win._on_push_branch("feature")
            qtbot.waitUntil(lambda: win._commands.force_push.execute.called, timeout=5000)
            _wait_until_idle(qtbot, win)
    deliver_queued_answers()

    assert gone_during_the_offer == [gui_thread]
    win._commands.force_push.execute.assert_called_once_with("origin", "feature")
    assert destroyed_on == [gui_thread, gui_thread]  # and the force push's own went the same way
