"""A diff the working-tree pane cannot load leaves a trace in the log and a
notice where the diff would have been.

Without the log line, whoever investigates has nothing to start from; without
the notice, the file's block shows loading bars for good.

Each test waits for its worker's answer to land before it ends, so the
answer cannot arrive in a later test.
"""

from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit

from git_gui.domain.entities import Hunk, LineKind, StagingState
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit


@pytest.fixture
def gate():
    released = threading.Event()
    yield released
    released.set()


@pytest.fixture
def queries(gate):
    def _diff_map(_paths):
        gate.wait(5)
        return {}

    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    queries.get_staged_diff.execute.return_value = []
    queries.get_file_diff.execute.return_value = []
    queries.get_working_tree_diff_map.execute.side_effect = _diff_map
    return queries


@pytest.fixture
def widget(qtbot, queries, caplog):
    caplog.set_level(logging.WARNING, logger="git_gui.presentation.widgets.hunk_diff")
    with workers_joined_on_exit():
        w = HunkDiffWidget(queries, MagicMock())
        qtbot.addWidget(w)
        yield w


def _failing_after(gate: threading.Event, message: str):
    def _fail(*_args):
        gate.wait(5)
        raise RuntimeError(message)

    return _fail


def test_a_failed_load_of_every_files_diff_is_logged(widget, queries, gate, qtbot, caplog):
    queries.get_working_tree_diff_map.execute.side_effect = _failing_after(gate, "index is corrupt")

    widget.load_all_files(["a.txt"])
    with qtbot.waitSignal(widget._load_all_signals.done, timeout=2000):
        gate.set()

    assert "index is corrupt" in caplog.text


def _assert_notices_not_skeletons(widget: HunkDiffWidget, expected: int) -> None:
    assert widget.findChildren(QFrame, "skeletonBar") == []
    notices = [
        label for label in widget.findChildren(QLabel) if "could not be loaded" in label.text()
    ]
    assert len(notices) == expected


def test_a_failed_load_of_every_files_diff_leaves_a_notice_in_each_block(
    widget, queries, gate, qtbot
):
    queries.get_working_tree_diff_map.execute.side_effect = _failing_after(gate, "index is corrupt")
    widget.resize(700, 600)
    widget.show()

    widget.load_all_files(["a.txt", "b.txt"])
    gate.set()

    qtbot.waitUntil(lambda: _assert_notices_not_skeletons(widget, 2), timeout=5000)


def test_a_file_the_diff_query_left_out_gets_a_notice_while_the_others_render(
    widget, queries, qtbot
):
    """A file another process holds open is skipped with a log line and the
    rest of the map comes back; its block kept the loading bars."""
    hunk = Hunk(header="@@ -1 +1 @@", lines=[(LineKind.ADDED, "kept\n")])
    queries.get_working_tree_diff_map.execute.side_effect = lambda _paths: {
        "a.txt": {StagingState.UNSTAGED: [hunk]}
    }
    widget.resize(700, 600)
    widget.show()

    widget.load_all_files(["a.txt", "b.txt"])

    qtbot.waitUntil(lambda: _assert_notices_not_skeletons(widget, 1), timeout=5000)
    assert "kept" in "".join(editor.toPlainText() for editor in widget.findChildren(QPlainTextEdit))


def test_a_failed_load_of_one_files_diff_is_logged(widget, queries, gate, qtbot, caplog):
    queries.get_file_diff.execute.side_effect = _failing_after(gate, "blob is unreadable")

    widget.load_file("a.txt")
    with qtbot.waitSignal(widget._load_signals.done, timeout=2000):
        gate.set()

    assert "blob is unreadable" in caplog.text


def test_a_failed_submodule_listing_is_logged(widget, queries, gate, qtbot, caplog):
    queries.list_submodules.execute.side_effect = RuntimeError(".gitmodules is unreadable")

    widget.load_all_files(["a.txt"])
    with qtbot.waitSignal(widget._load_all_signals.done, timeout=2000):
        gate.set()

    assert ".gitmodules is unreadable" in caplog.text
