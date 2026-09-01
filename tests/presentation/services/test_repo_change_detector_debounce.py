"""Debounce behaviour of RepoChangeDetector — bursts of events coalesce into
a single reload callback.

These used to wait a fixed number of milliseconds and assume the machine kept
up: the coalescing test fired five events across 150 ms inside a 200 ms window,
so one slow moment let the timer fire mid-storm and the run failed. The windows
are arguments now, so each test can pick timings where the expected outcome is
the only possible one, and waits are on conditions rather than on the clock.
"""

from __future__ import annotations

import pytest

from git_gui.presentation.services.repo_change_detector import RepoChangeDetector

# Long enough that no plausible scheduling delay reaches it, so a burst cannot
# leak a reload while the test is still sending events.
NEVER_DURING_A_TEST_MS = 30_000
# Short enough to wait for, but not so short that "not yet" is unobservable.
QUICK_MS = 50


@pytest.fixture
def make_detector(qtbot, tmp_path):
    """Build a detector rooted in an empty temp directory.

    The .git/ watch paths all fail to add (the directory is missing), which is
    fine — only the debouncer is exercised here.
    """
    built = []

    def _make(*, debounce_ms: int = QUICK_MS, suppress_ms: int = NEVER_DURING_A_TEST_MS):
        calls: list[None] = []
        d = RepoChangeDetector(
            str(tmp_path),
            on_reload=lambda: calls.append(None),
            debounce_ms=debounce_ms,
            suppress_ms=suppress_ms,
        )
        # A plain QObject, not a QWidget, so it is not registered with qtbot;
        # this list keeps it alive for the test's duration.
        built.append(d)
        return d, calls

    yield _make
    for d in built:
        d.stop()


def test_a_single_event_fires_one_reload(make_detector, qtbot):
    d, calls = make_detector()

    d._schedule_reload()
    assert calls == [], "the debouncer has not elapsed yet"

    qtbot.waitUntil(lambda: len(calls) == 1)


def test_events_within_the_window_coalesce_into_one_reload(make_detector, qtbot):
    """The window is longer than the test could possibly take.

    That is what makes this deterministic: with a 200 ms window and 150 ms of
    sending, a scheduling hiccup let the timer fire mid-burst.
    """
    d, calls = make_detector(debounce_ms=NEVER_DURING_A_TEST_MS)

    for _ in range(5):
        d._schedule_reload()
    assert calls == [], "five events, none of them elapsed"
    assert d._debouncer.isActive(), "the burst left one reload pending"

    # Collapse the wait rather than sleeping out a 30 s window.
    d._debouncer.setInterval(QUICK_MS)
    d._schedule_reload()
    qtbot.waitUntil(lambda: len(calls) == 1)
    qtbot.wait(QUICK_MS * 3)
    assert len(calls) == 1, "the burst produced exactly one reload"


def test_events_further_apart_than_the_window_fire_separately(make_detector, qtbot):
    d, calls = make_detector()

    d._schedule_reload()
    qtbot.waitUntil(lambda: len(calls) == 1)
    d._schedule_reload()
    qtbot.waitUntil(lambda: len(calls) == 2)


def test_stop_cancels_a_pending_reload(make_detector, qtbot):
    d, calls = make_detector()

    d._schedule_reload()
    d.stop()

    qtbot.wait(QUICK_MS * 4)
    assert calls == []


def test_our_own_writes_do_not_trigger_a_reload(make_detector, qtbot):
    """After GitCrisp reloads, the filesystem events its writes cause are ours."""
    d, calls = make_detector(suppress_ms=NEVER_DURING_A_TEST_MS)

    d.notify_self_reload()
    d._schedule_reload()

    qtbot.wait(QUICK_MS * 4)
    assert calls == []
    assert not d._debouncer.isActive(), "the event was dropped, not merely delayed"


def test_focus_returning_reloads_even_inside_the_suppression_window(make_detector, qtbot):
    """A focus event is the user coming back, not a consequence of our writes."""
    d, calls = make_detector(suppress_ms=NEVER_DURING_A_TEST_MS)

    d.notify_self_reload()
    d._schedule_reload_force()

    qtbot.waitUntil(lambda: len(calls) == 1)


def test_stop_is_idempotent_and_quiet(make_detector, qtbot, recwarn):
    """The second stop() must not warn.

    It claimed to be idempotent behind a try/except, but Qt warns rather than
    raising when disconnecting something that is not connected — so the except
    caught nothing and every suite run printed the warning.
    """
    d, _ = make_detector()

    d.stop()
    d.stop()

    disconnect_warnings = [w for w in recwarn.list if "Failed to disconnect" in str(w.message)]
    assert disconnect_warnings == []
