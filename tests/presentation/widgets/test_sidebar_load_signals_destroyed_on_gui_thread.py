"""A sidebar load's signals are deleted by Qt on the GUI thread, never by a worker.

The window reloads the sidebar after every operation, whenever it regains focus and on
every repo switch, and each load hands its worker a signals object to answer through.
Parentless, a newer load's replacing the sidebar's reference left the worker of the older
one the last to let go, and a closed sidebar's wrapper, kept alive by a reference cycle of
the theme listener, held the newest load's until the garbage collector reached it, on
whichever thread ran it. They belong to the application now (worker_signals) and go when
their worker has returned, so a sidebar closed under a running load leaves them alive
with nobody listening.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
import shiboken6

from git_gui.domain.entities import Branch
from git_gui.presentation.widgets import sidebar
from git_gui.presentation.widgets.sidebar import SidebarWidget
from tests.presentation.thread_helpers import HeldFirstCall, deliver_queued_answers, recording
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit


def _held_read(*, fails: bool) -> HeldFirstCall:
    """A branch read that parks the first worker asking; later reads answer at once."""
    return HeldFirstCall(list, fails_with=OSError("packed-refs is locked") if fails else None)


def _bus(get_branches: Callable[[], list[Branch]]) -> MagicMock:
    queries = MagicMock()
    queries.get_branches.execute.side_effect = get_branches
    queries.get_stashes.execute.return_value = []
    queries.get_tags.execute.return_value = []
    queries.list_local_branches_with_upstream.execute.return_value = []
    return queries


@pytest.fixture
def destroyed_on(monkeypatch) -> list[str]:
    """The name of the thread that destroyed each load's signals, as they are destroyed."""
    names: list[str] = []
    monkeypatch.setattr(sidebar, "_LoadSignals", recording(sidebar._LoadSignals, names))
    return names


HELD_LOADS = [pytest.param(False, id="answered"), pytest.param(True, id="failed")]


@pytest.mark.parametrize("held_load_fails", HELD_LOADS)
def test_a_superseded_loads_signals_are_destroyed_on_the_gui_thread(
    qtbot, destroyed_on, worker_errors, held_load_fails
):
    gui_thread = threading.current_thread().name
    older = _held_read(fails=held_load_fails)
    with workers_joined_on_exit():
        sb = SidebarWidget(_bus(older), MagicMock())
        qtbot.addWidget(sb)
        try:
            sb.reload()
            older_worker = older.gate.held_worker()  # inside its query, so the reload supersedes it
            sb.reload()
            qtbot.waitUntil(lambda: sb._model.rowCount() > 0, timeout=5000)
        finally:
            older.gate.open()
        older_worker.join(5)
        assert not older_worker.is_alive()
    deliver_queued_answers()

    assert [name for name in destroyed_on if name != gui_thread] == []
    assert len(destroyed_on) == 2  # one per load: the superseded one's did not outlive its worker
    assert worker_errors == []  # the held worker's emit reached live signals


@pytest.mark.parametrize("held_load_fails", HELD_LOADS)
def test_a_closed_sidebars_signals_outlive_it_until_the_worker_has_returned(
    destroyed_on, worker_errors, held_load_fails
):
    gui_thread = threading.current_thread().name
    held = _held_read(fails=held_load_fails)
    with workers_joined_on_exit():
        sb = SidebarWidget(_bus(held), MagicMock())
        try:
            sb.reload()
            worker = held.gate.held_worker()
            shiboken6.delete(sb)  # closed with the load still running
            deliver_queued_answers()
            # Deleted with the sidebar, they would be gone under a worker about to emit.
            assert destroyed_on == []
        finally:
            held.gate.open()
            if shiboken6.isValid(sb):  # the load never got going
                shiboken6.delete(sb)
        worker.join(5)
        assert not worker.is_alive()
    deliver_queued_answers()

    assert destroyed_on == [gui_thread]
    assert worker_errors == []
