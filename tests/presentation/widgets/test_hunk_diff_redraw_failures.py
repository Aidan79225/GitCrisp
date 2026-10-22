"""A file the working-tree pane cannot re-read after a stage or discard.

The single-file view redraws itself from the index after every command. A
working file held open by another process cannot be read, and that read fails
the same way every time. The redraw has to fall back as the first load does:
show what it could read, log the rest, and still tell the owner the file
changed, so the file list reloads.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QCheckBox, QMessageBox, QToolButton

from git_gui.domain.entities import Hunk, LineKind
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit

HUNK = Hunk(
    header="@@ -1,2 +1,2 @@",
    lines=[(LineKind.CONTEXT, "a\n"), (LineKind.REMOVED, "b\n"), (LineKind.ADDED, "B\n")],
)


def _unreadable(*_args):
    raise OSError("could not open 'a.txt': the file is in use")


@pytest.fixture
def queries():
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    queries.get_staged_diff.execute.return_value = []
    queries.get_file_diff.execute.return_value = []
    return queries


@pytest.fixture
def widget(qtbot, queries, caplog):
    caplog.set_level(logging.WARNING, logger="git_gui.presentation.widgets.hunk_diff")
    with workers_joined_on_exit():
        w = HunkDiffWidget(queries, MagicMock())
        qtbot.addWidget(w)
        w.show()
        yield w


def _checkboxes(widget: HunkDiffWidget) -> list[QCheckBox]:
    """The stage boxes of the block on screen, not of one torn down and not yet deleted."""
    item = widget._layout.itemAt(0)
    block = item.widget() if item else None
    return block.findChildren(QCheckBox) if block else []


def _show_one_file(widget: HunkDiffWidget, qtbot) -> None:
    widget.load_file("a.txt")
    qtbot.waitUntil(lambda: bool(_checkboxes(widget)), timeout=2000)


def test_unstaging_a_file_whose_working_copy_cannot_be_read_still_shows_its_staged_hunk(
    widget, queries, qtbot, caplog
):
    queries.get_staged_diff.execute.return_value = [HUNK]
    queries.get_file_diff.execute.side_effect = _unreadable
    _show_one_file(widget, qtbot)

    with qtbot.waitSignal(widget.hunk_toggled, timeout=1000):
        _checkboxes(widget)[0].click()

    widget._commands.unstage_hunk.execute.assert_called_once_with("a.txt", HUNK.header)
    assert len(_checkboxes(widget)) == 1, "the staged hunk is gone, leaving a blank pane"
    assert "the file is in use" in caplog.text


def test_discarding_a_hunk_then_failing_to_re_read_the_file_still_reports_the_discard(
    widget, queries, qtbot, caplog
):
    queries.get_file_diff.execute.return_value = [HUNK]
    _show_one_file(widget, qtbot)
    queries.get_file_diff.execute.side_effect = _unreadable
    discard = widget._layout.itemAt(0).widget().findChild(QToolButton, "discard_hunk")

    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        qtbot.waitSignal(widget.discard_hunk_requested, timeout=1000),
    ):
        discard.click()

    widget._commands.discard_hunk.execute.assert_called_once_with("a.txt", HUNK.header)
    assert widget._layout.count() > 0, "the file's block is gone, leaving a blank pane"
    assert "the file is in use" in caplog.text
