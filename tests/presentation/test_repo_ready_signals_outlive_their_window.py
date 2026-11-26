"""The window's repo-ready signals belong to the application, so letting go of the window frees nothing.

Every repo switch starts a worker that answers through the window's one signals object,
which serves every repo open for the window's life. Parentless, it died with its last
Python reference: on whichever thread the garbage collector ran when it reached the
window's wrapper, which a reference cycle (the repo list holds a lambda that names the
window) keeps alive after the window itself is gone. A child of the window would be
deleted with it, under a repo-open worker that is still inside its emit.

The signals are the application's, as a worker's own are (worker_signals), and live until
it exits. A window that goes away leaves them with nobody listening, so a worker finishing
after the window is gone has a live object to answer into and raises nothing. They are not
handed to delete_when_done, which frees a worker's signals when that worker returns: this
object serves every repo open, and the first worker to return would free it under the others.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import shiboken6

import git_gui.presentation.main_window.main_window as main_window_module
from git_gui.presentation.main_window import MainWindow
from git_gui.presentation.main_window.repo_lifecycle import _RepoReadySignals
from tests.presentation.thread_helpers import (
    HeldFirstCall,
    collect_garbage_on_another_thread,
    deliver_queued_answers,
    garbage_collected_only_where_the_test_says,
    recording,
)
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit
from tests.presentation.window_helpers import empty_repo_store

REPO = "/some/repo"


@pytest.fixture
def destroyed_on(monkeypatch) -> list[str]:
    """The name of the thread that destroyed each window's repo-ready signals, as they go."""
    names: list[str] = []
    monkeypatch.setattr(
        main_window_module, "_RepoReadySignals", recording(_RepoReadySignals, names)
    )
    return names


def _held_open(*, fails: bool) -> HeldFirstCall:
    """A session factory that parks the worker opening a repo until the test lets it go."""
    return HeldFirstCall(
        lambda: (MagicMock(), MagicMock()),
        fails_with=OSError("the repo is on a share that is down") if fails else None,
    )


OPENS = [pytest.param(False, id="opened"), pytest.param(True, id="failed")]


def _window(session_factory) -> MainWindow:
    return MainWindow(
        queries=None,
        commands=None,
        repo_store=empty_repo_store(),
        session_factory=session_factory,
    )


def test_the_signals_outlive_their_window_whichever_thread_collects_its_wrapper(destroyed_on):
    """Catches signals nobody owns, which the collector frees along with the dead window.

    Signals that were the window's child would be gone with it instead.
    """
    with garbage_collected_only_where_the_test_says():
        win = _window(lambda _path: (MagicMock(), MagicMock()))
        shiboken6.delete(win)  # the window is gone; its wrapper waits for the collector
        del win
        collect_garbage_on_another_thread()
    deliver_queued_answers()

    assert destroyed_on == []  # the application frees them, when it exits


@pytest.mark.parametrize("open_fails", OPENS)
def test_a_worker_finishing_after_its_window_was_destroyed_raises_nothing(
    worker_errors, open_fails
):
    """Catches signals that go with their window, so that the worker answers into nothing.

    It took them from the window before it was closed, and whether the repo opened or
    failed to, it answers once the window is gone: with signals that went along, the
    emit raises in the worker.
    """
    held = _held_open(fails=open_fails)
    with workers_joined_on_exit():
        win = _window(held)
        try:
            win._switch_repo(REPO)
            worker = held.gate.held_worker()
            shiboken6.delete(win)  # closed with the open still running
        finally:
            held.gate.open()
            if shiboken6.isValid(win):  # the open never got going
                shiboken6.delete(win)
        worker.join(5)
        assert not worker.is_alive()
    deliver_queued_answers()  # a slot of the dead window, if one were left connected, raises here

    assert worker_errors == []
