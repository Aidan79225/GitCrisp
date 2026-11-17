"""The signals a worker answers through belong to the application and are freed on the GUI thread.

The docstring of worker_signals says why. Pinned here: letting go of the signals does
not free them; they stay valid until the work has returned and are then deleted on the
GUI thread, also when the work raised, and its error still propagates; the answer is
delivered before they go; a wrapped worker keeps the name of its thread; and deleting
signals that are already gone raises nothing.
"""

from __future__ import annotations

import threading

import shiboken6
from PySide6.QtCore import QObject, Signal

from git_gui.presentation.widgets.background import delete_when_done, worker_signals
from tests.presentation.thread_helpers import Gate, deliver_queued_answers, recording
from tests.presentation.widgets.hunk_diff_helpers import wait_until_deleted


class _Signals(QObject):
    done = Signal(int)


def _run_on_a_worker(work) -> threading.Thread:
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    return worker


def test_letting_go_of_the_signals_does_not_delete_them(qapp):
    """A worker drops its reference when it returns; that must not be what frees them."""
    destroyed_on: list[str] = []

    worker_signals(recording(_Signals, destroyed_on))  # no reference kept

    assert destroyed_on == []
    for still_there in qapp.findChildren(_Signals):  # the application's, so ours to free
        still_there.deleteLater()
    deliver_queued_answers()
    assert destroyed_on == [threading.current_thread().name]


def test_the_signals_stay_valid_until_the_work_has_returned(qapp):
    """Freed any sooner, they would be gone under a worker that is about to emit."""
    signals = worker_signals(_Signals)
    in_work = Gate()

    worker = _run_on_a_worker(delete_when_done(signals, in_work.hold))
    try:
        in_work.held_worker()
        deliver_queued_answers()  # whatever has been asked to be deleted by now is deleted here
        assert shiboken6.isValid(signals)
    finally:
        in_work.open()
        worker.join(5)
        deliver_queued_answers()


def test_the_signals_are_deleted_on_the_gui_thread_once_the_work_returns(qapp):
    destroyed_on: list[str] = []
    signals = worker_signals(recording(_Signals, destroyed_on))

    _run_on_a_worker(delete_when_done(signals, lambda: None)).join(5)
    assert destroyed_on == []  # the worker only asked: Qt deletes them on the GUI thread

    deliver_queued_answers()

    assert destroyed_on == [threading.current_thread().name]


def test_a_work_that_raises_still_deletes_its_signals_and_still_raises(qapp, worker_errors):
    destroyed_on: list[str] = []
    signals = worker_signals(recording(_Signals, destroyed_on))

    def failing() -> None:
        raise ValueError("the read failed")

    _run_on_a_worker(delete_when_done(signals, failing)).join(5)
    deliver_queued_answers()

    assert [type(e) for e in worker_errors] == [ValueError]  # the work's own error is not swallowed
    assert destroyed_on == [threading.current_thread().name]


def test_the_answer_is_delivered_before_the_signals_go(qtbot):
    """A plain callable is dropped with its sender, so only the order of the two keeps the answer.

    The wait is a real event loop, which runs what was posted first first; the
    helper that drains the queue by hand runs every answer before any deletion
    and could not tell.
    """
    answers: list[int] = []
    signals = worker_signals(_Signals)
    signals.done.connect(answers.append)

    _run_on_a_worker(delete_when_done(signals, lambda: signals.done.emit(7))).join(5)
    wait_until_deleted(qtbot, signals)

    assert answers == [7]


def test_a_wrapped_worker_thread_is_still_named_after_its_work(qapp):
    """The app logs an uncaught error under the name of its thread, which is its target's."""

    def read_the_reflog() -> None:
        pass

    worker = _run_on_a_worker(delete_when_done(worker_signals(_Signals), read_the_reflog))
    worker.join(5)
    deliver_queued_answers()

    assert "read_the_reflog" in worker.name


def test_deleting_signals_that_are_already_gone_raises_nothing(qapp, worker_errors):
    """The application deletes its children as it is torn down, under a worker still running."""
    signals = worker_signals(_Signals)
    shiboken6.delete(signals)

    _run_on_a_worker(delete_when_done(signals, lambda: None)).join(5)

    assert worker_errors == []
