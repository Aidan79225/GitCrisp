"""A graph load's signals are deleted by Qt on the GUI thread, never by a worker.

Every reload hands its worker a signals object to answer through. Parentless, the graph
let go of a load's by rebinding the attribute that held it when the user opened another
repo while the load was in its query, which left the worker the last to let go; and a
destroyed graph's wrapper, kept alive by a reference cycle of the theme listener, held
the newest load's until the garbage collector reached it, on whichever thread ran it.
They belong to the application now (worker_signals) and go when their worker has
returned, so a graph destroyed under a running load leaves them alive with nobody
listening.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from unittest.mock import MagicMock

import pytest
import shiboken6

from git_gui.domain.entities import Commit
from git_gui.presentation.widgets import graph
from git_gui.presentation.widgets.graph import GraphWidget
from tests.presentation.thread_helpers import HeldFirstCall, deliver_queued_answers, recording
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit


def _commit(oid: str) -> Commit:
    return Commit(oid, oid, "A", datetime(2026, 1, 1), [])


def _repo(oid: str, *, walk: Callable[..., list[Commit]] | None = None) -> MagicMock:
    """A repo of one commit, whose commit graph `walk` reads if given."""
    queries = MagicMock()
    queries.get_commit_graph.execute.side_effect = walk or (lambda **_kwargs: [_commit(oid)])
    queries.get_branches.execute.return_value = []
    queries.get_tags.execute.return_value = []
    queries.is_dirty.execute.return_value = False
    queries.get_head_oid.execute.return_value = ""
    queries.get_repo_state.execute.return_value = None
    queries.get_merge_head.execute.return_value = None
    return queries


def _held_walk(oid: str, *, fails: bool) -> HeldFirstCall:
    """The first walk of the commit graph waits for the test, and fails when let go if told to."""
    return HeldFirstCall(
        lambda: [_commit(oid)], fails_with=OSError(f"cannot read {oid}") if fails else None
    )


def _graph(queries: MagicMock) -> GraphWidget:
    return GraphWidget(queries, MagicMock(), repo_store=MagicMock())


@pytest.fixture
def destroyed_on(monkeypatch) -> list[str]:
    """The name of the thread that destroyed each load's signals, in the order they went."""
    names: list[str] = []
    monkeypatch.setattr(graph, "_LoadSignals", recording(graph._LoadSignals, names))
    return names


# What starts a read of the commits on a worker.
LOADS = [pytest.param(GraphWidget.reload, id="reload")]
HELD_LOADS = [pytest.param(False, id="answered"), pytest.param(True, id="failed")]


def _supersede_a_held_load(qtbot, start_load, held_load_fails: bool):
    """Open another repo while a load is still in its query, then let the held load finish.

    Returns the graph and the failures it reported.
    """
    held = _held_walk("old", fails=held_load_fails)
    reported: list[str] = []
    with workers_joined_on_exit():
        widget = _graph(_repo("old", walk=held))
        qtbot.addWidget(widget)
        widget.load_failed.connect(reported.append)
        try:
            start_load(widget)
            held_worker = held.gate.held_worker()  # inside its query
            widget.set_buses(_repo("new"), MagicMock())  # the other repo supersedes the load
            qtbot.waitUntil(lambda: widget._row_of("new") is not None, timeout=5000)
        finally:
            held.gate.open()
        held_worker.join(5)
        assert not held_worker.is_alive()
    deliver_queued_answers()
    return widget, reported


@pytest.mark.parametrize("held_load_fails", HELD_LOADS)
@pytest.mark.parametrize("start_load", LOADS)
def test_a_superseded_loads_signals_are_destroyed_on_the_gui_thread(
    qtbot, qapp, destroyed_on, worker_errors, start_load, held_load_fails
):
    """Opening another repo lets go of a load still in its query; its worker must not free it."""
    _supersede_a_held_load(qtbot, start_load, held_load_fails)

    assert [name for name in destroyed_on if name != threading.current_thread().name] == []
    assert len(destroyed_on) == 2  # one per load: the superseded one's did not outlive its worker
    assert qapp.findChildren(graph._LoadSignals) == []  # and none is left over
    assert worker_errors == []  # the worker's emit reached live signals


@pytest.mark.parametrize("held_load_fails", HELD_LOADS)
@pytest.mark.parametrize("start_load", LOADS)
def test_a_superseded_loads_late_answer_is_dropped(qtbot, start_load, held_load_fails):
    """What the held load answered, once the other repo was open, is not shown."""
    widget, reported = _supersede_a_held_load(qtbot, start_load, held_load_fails)

    assert reported == []
    assert widget._row_of("old") is None
    assert widget._row_of("new") is not None


@pytest.mark.parametrize("held_load_fails", HELD_LOADS)
@pytest.mark.parametrize("start_load", LOADS)
def test_a_deleted_graphs_signals_outlive_it_until_the_worker_has_returned(
    destroyed_on, worker_errors, start_load, held_load_fails
):
    """A graph destroyed under a running load must not take its signals down with it."""
    gui_thread = threading.current_thread().name
    held = _held_walk("old", fails=held_load_fails)
    with workers_joined_on_exit():
        widget = _graph(_repo("old", walk=held))
        try:
            start_load(widget)
            worker = held.gate.held_worker()
            shiboken6.delete(widget)  # destroyed with the load still running
            deliver_queued_answers()  # whatever destroying it asked Qt to delete goes here
            # Deleted with the graph, they would be gone under a worker about to emit.
            assert destroyed_on == []
        finally:
            held.gate.open()
            if shiboken6.isValid(widget):  # the load never got going
                shiboken6.delete(widget)
        worker.join(5)
        assert not worker.is_alive()
    deliver_queued_answers()

    assert destroyed_on == [gui_thread]
    assert worker_errors == []
