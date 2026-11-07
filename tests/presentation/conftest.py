"""Fixtures shared by the presentation tests."""

from __future__ import annotations

import threading

import pytest


@pytest.fixture
def git_stops():
    """Set by the test when git should finish dying; set at the end so no worker is left waiting."""
    stops = threading.Event()
    yield stops
    stops.set()
