"""A reflog load's signals are deleted by Qt on the GUI thread, never by a worker.

Every load, the pane's own and each reload a window reload asks for, hands its worker
a signals object to answer through. Parentless, a reload left its worker the last to
let go of the previous load's, and a closed pane's wrapper, kept alive by a reference
cycle of the theme listener, held the newest load's until the garbage collector
reached it, on whichever thread ran it. They belong to the application now
(worker_signals), so neither deletes them, and a pane closed under a running load
leaves them alive with nobody listening.
"""

from __future__ import annotations

import threading
from datetime import datetime
from unittest.mock import MagicMock

import pytest
import shiboken6

from git_gui.domain.entities import ReflogEntry
from git_gui.presentation.widgets import reflog_pane
from git_gui.presentation.widgets.reflog_pane import ReflogPane
from tests.presentation.thread_helpers import HeldFirstCall, deliver_queued_answers, recording
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit


def _movements() -> list[ReflogEntry]:
    return [
        ReflogEntry(
            index=0,
            oid_new="a" * 40,
            oid_old="b" * 40,
            operation="commit",
            summary="a commit",
            committer="Alice",
            timestamp=datetime(2026, 1, 1, 12, 0),
            is_orphaned=False,
        )
    ]


def _held_reflog(*, fails: bool) -> HeldFirstCall:
    """A `get_reflog` that parks the worker of the pane's own first load; later reads answer at once."""
    return HeldFirstCall(_movements, fails_with=ValueError("index.lock exists") if fails else None)


def _queries(get_reflog) -> MagicMock:
    queries = MagicMock()
    queries.get_reflog.execute.side_effect = get_reflog
    queries.get_repo_state.execute.return_value.head_branch = "master"
    return queries


@pytest.fixture
def destroyed_on(monkeypatch) -> list[str]:
    """The name of the thread that destroyed each load's signals, as they are destroyed."""
    names: list[str] = []
    monkeypatch.setattr(reflog_pane, "_LoadSignals", recording(reflog_pane._LoadSignals, names))
    return names


HELD_LOADS = [pytest.param(False, id="answered"), pytest.param(True, id="failed")]


@pytest.mark.parametrize("held_load_fails", HELD_LOADS)
def test_a_superseded_loads_signals_are_destroyed_on_the_gui_thread(
    qtbot, destroyed_on, worker_errors, held_load_fails
):
    gui_thread = threading.current_thread().name
    held = _held_reflog(fails=held_load_fails)
    with workers_joined_on_exit():
        pane = ReflogPane(_queries(held))
        qtbot.addWidget(pane)
        try:
            held_worker = held.gate.held_worker()  # inside its query, so the reload supersedes it
            pane.reload()
            qtbot.waitUntil(lambda: pane._model.rowCount() == 1, timeout=5000)
        finally:
            held.gate.open()
        held_worker.join(5)
        assert not held_worker.is_alive()
    deliver_queued_answers()  # after the block: the newer load's worker has returned too

    assert [name for name in destroyed_on if name != gui_thread] == []
    assert len(destroyed_on) == 2  # one per load: the superseded one's did not outlive its worker
    assert worker_errors == []  # the held worker's emit reached live signals


@pytest.mark.parametrize("held_load_fails", HELD_LOADS)
def test_a_closed_panes_signals_outlive_it_until_the_worker_has_returned(
    destroyed_on, worker_errors, held_load_fails
):
    """The signals are still there when the pane is gone, and nothing deletes them under the worker.

    They are deleted once, on the GUI thread, after the worker has returned, and the
    worker raises nothing for having answered a pane that is no longer there.
    """
    gui_thread = threading.current_thread().name
    held = _held_reflog(fails=held_load_fails)
    with workers_joined_on_exit():
        pane = ReflogPane(_queries(held))
        try:
            worker = held.gate.held_worker()
            signals = pane._load_signals
            shiboken6.delete(pane)  # closed with the load still running
            deliver_queued_answers()  # whatever closing it asked Qt to delete goes here
            # Deleted with the pane, or as soon as it went, they would be gone under a worker
            # about to emit.
            assert shiboken6.isValid(signals)
        finally:
            held.gate.open()
            if shiboken6.isValid(pane):  # the load never got going
                shiboken6.delete(pane)
        worker.join(5)
        assert not worker.is_alive()
    deliver_queued_answers()

    assert destroyed_on == [gui_thread]
    assert worker_errors == []
