"""A hunk that covers a whole file goes to the file-level command.

`git apply` cannot stage or unstage the one hunk an untracked or newly added
file shows, and reversing a whole-file add or delete in the working tree
leaves the index confused, so those hunks are staged and discarded as files.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QCheckBox, QToolButton

from git_gui.domain.entities import Hunk, LineKind
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit

NEW_FILE = Hunk(header="@@ -0,0 +1,1 @@", lines=[(LineKind.ADDED, "new\n")])
DELETED_FILE = Hunk(header="@@ -1,1 +0,0 @@", lines=[(LineKind.REMOVED, "old\n")])
EDIT = Hunk(header="@@ -1,1 +1,1 @@", lines=[(LineKind.REMOVED, "b\n"), (LineKind.ADDED, "B\n")])


@pytest.fixture
def queries():
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    queries.get_staged_diff.execute.return_value = []
    queries.get_file_diff.execute.return_value = []
    return queries


@pytest.fixture
def widget(qtbot, queries):
    with workers_joined_on_exit():
        w = HunkDiffWidget(queries, MagicMock())
        qtbot.addWidget(w)
        yield w


def _block(widget: HunkDiffWidget):
    item = widget._layout.itemAt(0)
    return item.widget() if item else None


def _show(widget: HunkDiffWidget, qtbot, staged: list[Hunk], unstaged: list[Hunk]):
    widget._queries.get_staged_diff.execute.return_value = staged
    widget._queries.get_file_diff.execute.return_value = unstaged
    widget.load_file("a.txt")
    qtbot.waitUntil(lambda: _block(widget) is not None, timeout=2000)
    return _block(widget)


def test_ticking_an_untracked_files_hunk_stages_the_file(widget, qtbot):
    _show(widget, qtbot, [], [NEW_FILE]).findChild(QCheckBox).click()

    widget._commands.stage_files.execute.assert_called_once_with(["a.txt"])
    widget._commands.stage_hunk.execute.assert_not_called()


def test_unticking_a_staged_new_files_hunk_unstages_the_file(widget, qtbot):
    _show(widget, qtbot, [NEW_FILE], []).findChild(QCheckBox).click()

    widget._commands.unstage_files.execute.assert_called_once_with(["a.txt"])
    widget._commands.unstage_hunk.execute.assert_not_called()


def test_ticking_an_edit_stages_only_that_hunk(widget, qtbot):
    _show(widget, qtbot, [], [EDIT]).findChild(QCheckBox).click()

    widget._commands.stage_hunk.execute.assert_called_once_with("a.txt", EDIT.header)
    widget._commands.stage_files.execute.assert_not_called()


@pytest.mark.parametrize(
    "hunk, tooltip",
    [
        (NEW_FILE, "Discard this file"),
        (DELETED_FILE, "Discard this file"),
        (EDIT, "Discard this hunk"),
    ],
    ids=["added", "deleted", "edited"],
)
def test_a_whole_file_add_or_delete_is_discarded_as_a_file(widget, qtbot, hunk, tooltip):
    button = _show(widget, qtbot, [], [hunk]).findChild(QToolButton, "discard_hunk")

    assert button.toolTip() == tooltip
