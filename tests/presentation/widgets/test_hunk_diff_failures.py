"""A staging or discard command that fails, in the working-tree diff pane.

The checkbox is a plain widget with no model behind it, so after a failed
command only a redraw from the index can put it back; and the failure has to
reach the user, not just the log file.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox, QToolButton

from git_gui.domain.entities import Hunk, LineKind
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget

HUNK = Hunk(
    header="@@ -1,2 +1,2 @@",
    lines=[(LineKind.CONTEXT, "a\n"), (LineKind.REMOVED, "b\n"), (LineKind.ADDED, "B\n")],
)


@pytest.fixture
def commands():
    commands = MagicMock()
    commands.stage_hunk.execute.side_effect = RuntimeError("the index is locked")
    commands.discard_hunk.execute.side_effect = RuntimeError("patch does not apply")
    commands.discard_file.execute.side_effect = RuntimeError("permission denied")
    return commands


@pytest.fixture
def widget(qtbot, commands):
    """A pane showing one file, torn down only after its redraws have settled.

    A redraw leaves the old blocks to deleteLater, and destroying their
    editors queues a scrollbar re-measure; it has to run while the pane still
    exists, so the pane is not handed to qtbot, which would destroy it first.
    """
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    queries.get_staged_diff.execute.return_value = []
    queries.get_file_diff.execute.return_value = [HUNK]
    w = HunkDiffWidget(queries, commands)
    w.show()
    w.load_file("a.txt")
    qtbot.waitUntil(lambda: bool(_current_checkboxes(w)), timeout=2000)
    yield w
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qtbot.wait(10)
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _current_block(widget: HunkDiffWidget):
    item = widget._layout.itemAt(0)
    return item.widget() if item else None


def _current_checkboxes(widget: HunkDiffWidget) -> list[QCheckBox]:
    block = _current_block(widget)
    return block.findChildren(QCheckBox) if block else []


def _discard_button(widget: HunkDiffWidget) -> QToolButton:
    return next(
        b
        for b in _current_block(widget).findChildren(QToolButton)
        if b.toolTip() == "Discard this hunk"
    )


def test_a_failed_stage_leaves_the_hunk_unticked(widget):
    _current_checkboxes(widget)[0].click()

    assert [box.isChecked() for box in _current_checkboxes(widget)] == [False]


def test_a_failed_stage_is_reported(widget, qtbot):
    with qtbot.waitSignal(widget.operation_failed, timeout=1000) as failure:
        _current_checkboxes(widget)[0].click()

    assert "the index is locked" in failure.args[0]


def test_a_failed_discard_is_reported(widget, qtbot):
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        qtbot.waitSignal(widget.operation_failed, timeout=1000) as failure,
    ):
        _discard_button(widget).click()

    assert "patch does not apply" in failure.args[0]


def test_a_failed_file_discard_is_reported(widget, qtbot):
    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        qtbot.waitSignal(widget.operation_failed, timeout=1000) as failure,
    ):
        widget._on_discard_file_clicked("a.txt")

    assert "permission denied" in failure.args[0]
