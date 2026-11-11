"""Let a pane's workers finish before the pane is let go.

A pane's load signals are its children, so they are deleted with it, on the GUI
thread. A worker still inside its emit at that moment would be calling into an
object being torn down: a known residual, microseconds wide, that exists only
where a pane is destroyed. In the shipped app the diff panes are destroyed only
when the window closes, while a BlamePane is destroyed whenever the user closes
it. A worker left running also outlives its test, and answers or logs during a
later one. workers_joined_on_exit joins each worker for up to two seconds, which
keeps both out of the tests.
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
    """Wait for Qt to delete *obj*, a load's signals that delete themselves once answered.

    A waitSignal on those signals can lose its wake-up to that deletion: their
    own deleteLater is connected before any observer a test adds, so they can be
    gone before the observer is called. The pane's slot is connected before
    deleteLater, so by the time they are gone the pane has had the answer.
    """
    qtbot.waitUntil(lambda: not shiboken6.isValid(obj), timeout=timeout)
