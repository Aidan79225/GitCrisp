"""A blame load's signals are deleted by Qt on the GUI thread, never by a worker.

Blame before a commit, then go Back, while the first request is still running:
that load is held only by its worker. Its signals had no parent, so the worker
deleted a QObject it does not own on its own thread when it exited, which Qt
documents as unsafe and which ended a stress run of the diff panes in heap
corruption (test_load_signals_destroyed_on_gui_thread.py). A child of the pane
that deletes itself once answered is freed by Qt, on the GUI thread.

And the signals go with the pane, so a worker finishing after the pane is gone
must not fail for it.
"""

from __future__ import annotations

import threading
from datetime import datetime
from unittest.mock import MagicMock

import pytest
import shiboken6

from git_gui.domain.entities import BlameLine
from git_gui.presentation.widgets import blame_pane
from git_gui.presentation.widgets.blame_pane import BlamePane
from tests.presentation.thread_helpers import Gate, deliver_queued_answers, recording
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit

PATH = "src/app.py"
BLAMED_COMMIT = "a" * 40
OLDER = "b" * 40  # the parent of BLAMED_COMMIT, where "Blame before" walks back to


def _blame() -> list[BlameLine]:
    return [
        BlameLine(
            line_no=1,
            text="first",
            commit_oid=BLAMED_COMMIT,
            author="Alice",
            timestamp=datetime(2026, 1, 1),
            summary="did a thing",
            is_run_start=True,
        )
    ]


class _HeldBlame:
    """A `get_blame` that parks the worker asking for one revision until the test lets it go."""

    def __init__(self, revision: str | None, *, fails: bool) -> None:
        self._revision = revision
        self._fails = fails
        self.gate = Gate()

    def __call__(self, path: str, at_oid: str | None = None) -> list[BlameLine]:
        if at_oid != self._revision:
            return _blame()
        self.gate.hold()
        if self._fails:
            raise ValueError(f"{path} does not exist at {at_oid}")
        return _blame()


def _pane(blame: _HeldBlame) -> BlamePane:
    queries = MagicMock()
    queries.get_blame.execute.side_effect = blame
    queries.get_commit_detail.execute.return_value = MagicMock(parents=[OLDER])
    return BlamePane(queries, PATH)


HELD_LOADS = [pytest.param(False, id="answered"), pytest.param(True, id="failed")]


@pytest.mark.parametrize("held_load_fails", HELD_LOADS)
def test_a_superseded_loads_signals_are_destroyed_on_the_gui_thread(
    qtbot, monkeypatch, held_load_fails
):
    gui_thread = threading.current_thread().name
    destroyed_on: list[str] = []
    monkeypatch.setattr(
        blame_pane, "_LoadSignals", recording(blame_pane._LoadSignals, destroyed_on)
    )
    older = _HeldBlame(OLDER, fails=held_load_fails)
    with workers_joined_on_exit():
        pane = _pane(older)
        qtbot.addWidget(pane)
        qtbot.waitUntil(lambda: len(pane._editor._lines) == 1, timeout=5000)
        try:
            pane._blame_before(BLAMED_COMMIT)
            older.gate.held_worker()  # inside its query, so the load Back starts supersedes it
            pane._go_back()
            qtbot.waitUntil(lambda: pane._status.full_text() == f"{PATH} @ HEAD", timeout=5000)
        finally:
            older.gate.open()
    deliver_queued_answers()

    assert [name for name in destroyed_on if name != gui_thread] == []
    assert len(destroyed_on) == 3  # one per load: none outlived its answer


@pytest.mark.parametrize("held_load_fails", HELD_LOADS)
def test_a_worker_finishing_after_its_pane_was_destroyed_raises_nothing(
    monkeypatch, held_load_fails
):
    raised: list[BaseException | None] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: raised.append(args.exc_value))
    held = _HeldBlame(None, fails=held_load_fails)  # the pane's own first load, of HEAD
    with workers_joined_on_exit():
        pane = _pane(held)
        try:
            worker = held.gate.held_worker()
            shiboken6.delete(pane)  # closed with the load still running
        finally:
            held.gate.open()
            if shiboken6.isValid(pane):  # the load never got going
                shiboken6.delete(pane)
        worker.join(5)
        assert not worker.is_alive()

    assert raised == []
