"""Fixtures shared by the presentation tests."""

from __future__ import annotations

import threading

import pytest


@pytest.fixture
def worker_errors(monkeypatch) -> list[BaseException | None]:
    """What the threads that die of an error during the test raised, collected, not printed."""
    errors: list[BaseException | None] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: errors.append(args.exc_value))
    return errors


@pytest.fixture
def git_stops():
    """Set by the test when git should finish dying; set at the end so no worker is left waiting."""
    stops = threading.Event()
    yield stops
    stops.set()
