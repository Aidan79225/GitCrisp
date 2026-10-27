"""After a stage, unstage or discard, the all-files view's other hunks wait.

The owner rebuilds the all-files view once the file list has been read again,
off the UI thread. Until then every other hunk still carries the header it was
drawn with, and a stage can shift the line numbers in the headers below it, so
a second click in that gap names a hunk the index no longer has.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QCheckBox, QMessageBox, QToolButton

from git_gui.domain.entities import Hunk, LineKind, StagingState
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit

PATH = "f.txt"
FIRST = Hunk(header="@@ -8,6 +8,7 @@", lines=[(LineKind.ADDED, "a\n")])
SECOND = Hunk(header="@@ -58,6 +59,7 @@", lines=[(LineKind.ADDED, "b\n")])


@pytest.fixture
def widget(qtbot):
    """A shown all-files pane holding one file with two unstaged hunks."""
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    queries.get_working_tree_diff_map.execute.return_value = {
        PATH: {StagingState.UNSTAGED: [FIRST, SECOND]}
    }
    with workers_joined_on_exit():
        w = HunkDiffWidget(queries, MagicMock())
        qtbot.addWidget(w)
        w.resize(800, 500)
        w.show()
        w.load_all_files([PATH])
        qtbot.waitUntil(lambda: len(_checkboxes(w)) == 2, timeout=2000)
        yield w


def _block(widget: HunkDiffWidget):
    return widget._aggregate_blocks[PATH]


def _checkboxes(widget: HunkDiffWidget) -> list[QCheckBox]:
    return _block(widget).findChildren(QCheckBox)


def _discard_buttons(widget: HunkDiffWidget) -> list[QToolButton]:
    return [
        b for b in _block(widget).findChildren(QToolButton) if b.toolTip() == "Discard this hunk"
    ]


def test_ticking_a_hunk_leaves_the_others_unclickable_until_the_reload(widget):
    first, second = _checkboxes(widget)

    first.click()

    assert not second.isEnabled()


def test_discarding_a_hunk_leaves_the_others_unclickable_until_the_reload(widget, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    first, second = _discard_buttons(widget)

    first.click()

    assert not second.isEnabled()


def test_the_owners_reload_makes_the_hunks_clickable_again(widget, qtbot):
    _checkboxes(widget)[0].click()

    widget.load_all_files([PATH])
    qtbot.waitUntil(lambda: len(_checkboxes(widget)) == 2, timeout=2000)

    assert all(box.isEnabled() for box in _checkboxes(widget))


STAGED_EDIT = Hunk(header="@@ -1,6 +1,6 @@", lines=[(LineKind.ADDED, "c\n")])
WHOLE_FILE_DELETION = Hunk(header="@@ -1,10 +0,0 @@", lines=[(LineKind.REMOVED, "c\n")])


@pytest.fixture
def deleted_after_staging(qtbot):
    """A shown all-files pane holding one file with a staged edit, then deleted
    from the work tree, so its unstaged side is a whole-file deletion."""
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    queries.get_working_tree_diff_map.execute.return_value = {
        PATH: {StagingState.STAGED: [STAGED_EDIT], StagingState.UNSTAGED: [WHOLE_FILE_DELETION]}
    }
    with workers_joined_on_exit():
        w = HunkDiffWidget(queries, MagicMock())
        qtbot.addWidget(w)
        w.resize(800, 500)
        w.show()
        w.load_all_files([PATH])
        qtbot.waitUntil(lambda: len(_checkboxes(w)) == 2, timeout=2000)
        yield w


def test_discarding_a_whole_file_leaves_its_other_hunks_unclickable_until_the_reload(
    deleted_after_staging, monkeypatch
):
    """Discarding the file resets its index too, so the staged hunk's header
    names a hunk the index no longer has."""
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    staged = next(box for box in _checkboxes(deleted_after_staging) if box.isChecked())
    discard_file = next(
        b
        for b in _block(deleted_after_staging).findChildren(QToolButton)
        if b.toolTip() == "Discard this file"
    )

    discard_file.click()

    assert not staged.isEnabled()
