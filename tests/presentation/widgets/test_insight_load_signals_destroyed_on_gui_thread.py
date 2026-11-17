"""An Insight walk's signals are deleted by Qt on the GUI thread, never by a worker.

Each walk hands its worker a signals object to report through. A walk the dialog gives
up on, because the user chose another range or closed the dialog, is cancelled and
answers nothing, and its worker notices the cancel only at its next commit. Parentless,
that worker was the last to let go of the signals when another range had replaced the
dialog's reference, and a closed dialog's wrapper, kept alive by a reference cycle of the
theme listener, held them until the garbage collector reached it, on whichever thread ran
it. They belong to the application now (worker_signals) and go when their worker returns,
answered or not, so a dialog closed under a running walk leaves them alive with nobody
listening.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
import shiboken6
from PySide6.QtWidgets import QWidget

from git_gui.presentation.widgets import insight_dialog
from git_gui.presentation.widgets.insight_dialog import InsightDialog, InsightRange
from tests.presentation.thread_helpers import HeldFirstCall, deliver_queued_answers, recording
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit


def _held_walk(*, fails: bool) -> HeldFirstCall:
    """A `get_commit_stats` that parks the dialog's own first walk; later walks find no commits.

    The held one, let go, finds none either, or fails.
    """
    return HeldFirstCall(lambda: iter(()), fails_with=OSError("git log died") if fails else None)


def _queries_walking(walk: HeldFirstCall) -> MagicMock:
    queries = MagicMock()
    queries.get_commit_stats.execute.side_effect = walk
    return queries


@pytest.fixture
def window(qtbot) -> QWidget:
    """Stands in for the main window, which the dialog is parented to, as in the app."""
    window = QWidget()
    qtbot.addWidget(window)
    return window


@pytest.fixture
def destroyed_on(monkeypatch) -> list[str]:
    """The name of the thread that destroyed each walk's signals, as they are destroyed."""
    names: list[str] = []
    monkeypatch.setattr(
        insight_dialog, "_LoadSignals", recording(insight_dialog._LoadSignals, names)
    )
    return names


HELD_WALKS = [pytest.param(False, id="completes"), pytest.param(True, id="fails")]


@pytest.mark.parametrize("held_walk_fails", HELD_WALKS)
def test_a_superseded_walks_signals_are_destroyed_on_the_gui_thread(
    qtbot, qapp, window, destroyed_on, held_walk_fails
):
    gui_thread = threading.current_thread().name
    held = _held_walk(fails=held_walk_fails)
    with workers_joined_on_exit():
        dialog = InsightDialog(_queries_walking(held), window)
        try:
            held_worker = held.gate.held_worker()  # inside its walk, so another range supersedes it
            dialog._range_buttons[InsightRange.ALL].click()
            qtbot.waitUntil(lambda: dialog._last_render is not None, timeout=5000)
        finally:
            held.gate.open()
        held_worker.join(5)
        assert not held_worker.is_alive()
    deliver_queued_answers()

    assert [name for name in destroyed_on if name != gui_thread] == []
    # One per walk. The superseded one was cancelled and answered nothing, so no answer
    # could be what freed its signals.
    assert len(destroyed_on) == 2
    assert qapp.findChildren(insight_dialog._LoadSignals) == []  # and none is left over


def _destroyed(dialog: InsightDialog) -> None:
    shiboken6.delete(dialog)


def _closed(dialog: InsightDialog) -> None:
    """Esc: the dialog cancels its walk, and Qt deletes it once the event loop is back."""
    dialog.reject()
    deliver_queued_answers()


def _let_go_while_walking(window, held: HeldFirstCall, let_go) -> threading.Thread:
    """Open a dialog, wait for its walk to be inside the query, let the dialog go."""
    dialog = InsightDialog(_queries_walking(held), window)
    worker = held.gate.held_worker()  # inside its walk, so the walk is out as the dialog goes
    let_go(dialog)
    return worker  # the opener lets go of its dialog here


@pytest.mark.parametrize("held_walk_fails", HELD_WALKS)
@pytest.mark.parametrize("let_go", [_destroyed, _closed])
def test_a_dialogs_signals_outlive_it_until_the_walk_has_returned(
    window, destroyed_on, worker_errors, let_go, held_walk_fails
):
    gui_thread = threading.current_thread().name
    held = _held_walk(fails=held_walk_fails)
    with workers_joined_on_exit():
        try:
            worker = _let_go_while_walking(window, held, let_go)
            deliver_queued_answers()
            # Deleted with the dialog, they would be gone under a worker about to emit.
            assert destroyed_on == []
        finally:
            held.gate.open()
        worker.join(5)
        assert not worker.is_alive()
    deliver_queued_answers()

    assert destroyed_on == [gui_thread]
    assert worker_errors == []
