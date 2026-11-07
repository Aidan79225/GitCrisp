"""Let a pane's diff workers finish before the pane is let go.

A pane's load signals are its children, so they are deleted with it, on the GUI
thread. A worker still inside its emit at that moment would be calling into an
object being torn down: a known residual, microseconds wide, that exists only
where a pane is destroyed (in the shipped app, when the window closes). A
worker left running also outlives its test, and answers or logs during a later
one. Joining the workers before the pane goes rules out both.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def workers_joined_on_exit() -> Iterator[None]:
    """Join every thread started inside the block before leaving it.

    No worker is then still emitting into a pane as it is destroyed, or
    running on into a later test.
    """
    before = set(threading.enumerate())
    try:
        yield
    finally:
        for thread in set(threading.enumerate()) - before:
            thread.join(2)
