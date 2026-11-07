"""Helpers for the tests that pin which thread a worker's signals are freed on.

Qt documents deleting a QObject from a thread other than its own as unsafe. Each
of those tests holds a worker inside its query, lets the pane move on, and reads
the name of the thread that ran the signals' C++ destructor.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt


def recording(base: type[QObject], destroyed_on: list[str]) -> type[QObject]:
    """*base*, noting from its C++ destructor the name of the thread that ran it.

    The ``destroyed`` connection has to be direct. A queued one is delivered, if
    at all, after the destructor has finished, so *destroyed_on* stays empty and
    every test that reads it fails on correct code.
    """

    class Recording(base):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.destroyed.connect(
                lambda *_: destroyed_on.append(threading.current_thread().name),
                Qt.ConnectionType.DirectConnection,
            )

    return Recording


def deliver_queued_answers() -> None:
    """Run the slots the workers queued, then the deletions those slots scheduled."""
    for _ in range(2):
        QCoreApplication.sendPostedEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class Gate:
    """Holds a worker inside its query until the test lets it go."""

    def __init__(self) -> None:
        self.holder: threading.Thread | None = None
        self._entered = threading.Event()
        self._open = threading.Event()

    def hold(self) -> None:
        """Called by the worker: say it is in, then wait."""
        self.holder = threading.current_thread()
        self._entered.set()
        self._open.wait(5)

    def held_worker(self) -> threading.Thread:
        """The worker inside the query, once it is there."""
        assert self._entered.wait(5), "the held load never reached its query"
        assert self.holder is not None
        return self.holder

    def open(self) -> None:
        self._open.set()
