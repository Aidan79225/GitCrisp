from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from contextlib import suppress

from PySide6.QtCore import QCoreApplication, QObject

# Starts a widget's slow work off the GUI thread. Widgets take one as a
# parameter, so a test can hold the work and run it in the order it chooses.
BackgroundRunner = Callable[[Callable[[], None]], None]


def start_daemon_thread(work: Callable[[], None]) -> None:
    """Run *work* on a daemon thread, so work still going never holds the app open."""
    threading.Thread(target=work, daemon=True).start()


def worker_signals[SignalsT: QObject](signals_type: type[SignalsT]) -> SignalsT:
    """The signals a worker answers through, owned by the application.

    A parentless QObject made in Python belongs to its wrapper: whichever thread
    drops the last reference deletes it, and Qt documents deleting a QObject from
    a thread other than its own as unsafe. When a newer load has replaced the
    widget's reference that thread is the worker's, which keeps its signals until
    it returns. When the widget was closed it is whichever thread the garbage
    collector runs on, because a reference cycle (the theme listener's, or a lambda
    that names the widget) keeps the widget's wrapper, and the reference it holds,
    alive after its C++ object is gone.

    Owned by the application, the signals are deleted only by delete_when_done,
    on the GUI thread, or with the application. A widget that goes away leaves
    them alive with nobody listening. Signals that are a child of their widget, as
    several panes and dialogs still make theirs, go with it, and a worker that is
    inside its emit at that moment is calling into an object being torn down: new
    workers should use this instead. The application as parent only matters for
    signals that nothing hands to delete_when_done: once deleteLater has been
    asked for, PySide gives even a parentless object to Qt, which deletes it on
    the GUI thread, whereas without that call the thread that drops the last
    reference deletes it.

    Build one per worker and hand it to delete_when_done: shared, the first worker
    to return would delete them under the others. The exception is an object that
    serves a window for its whole life, MainWindow's repo-ready signals: built once
    and never handed over, it lives until the application exits. Call it on the GUI
    thread. Off it Qt refuses the parent and warns, and the signals stay parentless,
    living in the caller's thread.
    """
    return signals_type(QCoreApplication.instance())


def delete_when_done(signals: QObject, work: Callable[[], None]) -> Callable[[], None]:
    """*work*, asking Qt to delete *signals* once it has returned or raised.

    Qt deletes them on the thread they live in, the GUI thread for worker_signals,
    after the answers the work has queued. A plain callable connected to the
    signals is dropped with them, so it receives its answers only because the
    deletion is asked for after the last one. A work that returns without
    answering (a cancelled read, say) still frees its signals.
    """

    # wraps keeps the thread named after its work: logging_setup logs an uncaught
    # error of a worker under the name of its thread.
    @functools.wraps(work)
    def run() -> None:
        try:
            work()
        finally:
            # The application deletes its children as it is torn down, which can
            # happen under a worker that is still running: they are gone, and
            # there is nothing left to delete.
            with suppress(RuntimeError):
                signals.deleteLater()

    return run
