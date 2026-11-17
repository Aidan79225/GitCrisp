"""Helpers for the tests of code that runs its work on worker threads.

workers_joined_on_exit lets the workers a test starts finish before it ends. A
worker left running outlives its test, and answers or logs during a later one;
joining each for up to two seconds keeps that out of the tests. It also matters
where a pane's load signals are its children, as the diff panes' and a
BlamePane's are: they are deleted with the pane, on the GUI thread, and a worker
still inside its emit at that moment would be calling into an object being torn
down, a known residual, microseconds wide. In the shipped app the diff panes are
destroyed only when the window closes, while a BlamePane is destroyed whenever
the user closes it. Signals that belong to the application (worker_signals) have
no such residual.

wait_until_deleted waits for a load's signals to be deleted. Signals that delete
themselves once answered can be gone before a waitSignal on them is woken, so a
test waits for the deletion itself.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import shiboken6
from PySide6.QtCore import QObject


@contextmanager
def workers_joined_on_exit() -> Iterator[None]:
    """Join every thread started inside the block, up to two seconds each, before leaving it.

    A worker that finishes within that time is no longer emitting into a pane
    destroyed after the block, nor running on into a later test.
    """
    before = set(threading.enumerate())
    try:
        yield
    finally:
        for thread in set(threading.enumerate()) - before:
            thread.join(2)


def wait_until_deleted(qtbot, obj: QObject, timeout: int = 2000) -> None:
    """Wait for Qt to delete *obj*, the signals of a load or of a worker.

    A waitSignal on signals that delete themselves once answered can lose its
    wake-up to that deletion: their own deleteLater is connected before any
    observer a test adds, so they can be gone before the observer is called. The
    pane's slot is connected before deleteLater, so by the time they are gone the
    pane has had the answer.
    """
    qtbot.waitUntil(lambda: not shiboken6.isValid(obj), timeout=timeout)
