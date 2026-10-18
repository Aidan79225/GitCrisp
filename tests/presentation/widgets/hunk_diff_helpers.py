"""Let a working-tree pane's diff workers finish before the pane is let go.

A worker keeps its signals object alive until the thread ends. If the test
drops the pane first, the worker's exit is what destroys that object, on a
thread that does not own it, and Qt can crash for it in a later test.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def workers_joined_on_exit() -> Iterator[None]:
    """Join every thread started inside the block before leaving it."""
    before = set(threading.enumerate())
    try:
        yield
    finally:
        for thread in set(threading.enumerate()) - before:
            thread.join(2)
