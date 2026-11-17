"""Helpers for the test files that pin which thread a QObject is freed on.

Qt documents deleting a QObject from a thread other than its own as unsafe, so
recording() notes the name of the thread that ran a QObject subclass's C++
destructor. Gate holds a worker where it is until the test lets it go, and
HeldFirstCall is a fake read whose first call waits at one. deliver_queued_answers()
lets Qt carry out every deletion asked for by then, by the workers themselves or by
the slots they queued.

The tests also join the workers they start with workers_joined_on_exit(), and wait
for a deletion with wait_until_deleted(); both live in widgets/hunk_diff_helpers.py.
"""

from __future__ import annotations

import copy
import itertools
import threading
from collections.abc import Callable

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
    """Carry out every deleteLater asked for so far, after what the workers queued for the GUI thread.

    That includes the deletions a worker asked for itself as it returned, and the
    ones the slots it queued ask for.
    """
    for _ in range(2):
        QCoreApplication.sendPostedEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class Gate:
    """Holds a worker where it calls hold(), whatever it is doing, until the test lets it go."""

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
        """The worker inside hold(), once it is there."""
        assert self._entered.wait(5), "the held worker never reached the gate"
        assert self.holder is not None
        return self.holder

    def open(self) -> None:
        self._open.set()


class HeldFirstCall:
    """A fake for what a worker calls: its first call waits at ``gate``, later ones answer at once.

    So a test can hold the first load while a second runs past it. The held call, let
    go, raises *fails_with* if given, and answers like every other call if not.
    """

    def __init__(
        self, answer: Callable[[], object], *, fails_with: BaseException | None = None
    ) -> None:
        self.gate = Gate()
        self._answer = answer
        self._fails_with = fails_with
        self._calls = itertools.count()

    def __call__(self, *_args, **_kwargs) -> object:
        if next(self._calls) == 0:
            self.gate.hold()
            if self._fails_with is not None:
                # A copy: a raised exception keeps its traceback, and so the frames of the
                # worker that raised it and the signals in them, for as long as it lives.
                raise copy.copy(self._fails_with)
        return self._answer()
