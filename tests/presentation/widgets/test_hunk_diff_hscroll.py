"""The working-tree pane's shared horizontal bar follows the file on screen."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from git_gui.domain.entities import Hunk, LineKind, StagingState
from git_gui.presentation.app_settings import set_side_by_side_diff
from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit

LONG_LINE_HUNK = Hunk(header="@@ -1,1 +1,1 @@", lines=[(LineKind.ADDED, "x" * 400 + "\n")])


def test_selecting_a_file_with_long_lines_shows_the_bar(qtbot):
    """Nothing was on screen before, so no torn-down editor can prompt a
    re-measure: selecting the file has to do it itself."""
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    queries.get_staged_diff.execute.return_value = []
    queries.get_file_diff.execute.return_value = [LONG_LINE_HUNK]
    widget = HunkDiffWidget(queries, MagicMock())
    qtbot.addWidget(widget)
    widget.resize(600, 400)
    widget.show()

    widget.load_file("long.txt")

    qtbot.waitUntil(lambda: widget._hscroll.isVisible(), timeout=2000)
    assert widget._hscroll.maximum() > 0


def test_a_re_measure_still_pending_when_the_pane_is_destroyed_is_dropped(qtbot):
    """Otherwise it reaches into the destroyed container and raises."""
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    widget = HunkDiffWidget(queries, MagicMock())
    widget.clear()

    widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qtbot.wait(20)


# ── After a collapsed block is expanded ──────────────────────────────────────

SIDE_BY_SIDE_HUNK = Hunk(
    header="@@ -1,1 +1,1 @@",
    lines=[(LineKind.REMOVED, "y" * 600 + "\n"), (LineKind.ADDED, "x" * 600 + "\n")],
)


@pytest.fixture
def side_by_side():
    """Two editors share each row, so a page of the whole pane is two pages."""
    set_side_by_side_diff(True)
    yield
    set_side_by_side_diff(False)


@pytest.fixture
def pane(qtbot):
    """A shown pane whose one changed file has a line far wider than the pane."""
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    queries.get_staged_diff.execute.return_value = []
    queries.get_file_diff.execute.return_value = [SIDE_BY_SIDE_HUNK]
    queries.get_working_tree_diff_map.execute.return_value = {
        "long.txt": {StagingState.UNSTAGED: [SIDE_BY_SIDE_HUNK]}
    }
    with workers_joined_on_exit():
        widget = HunkDiffWidget(queries, MagicMock())
        qtbot.addWidget(widget)
        widget.resize(900, 600)
        widget.show()
        yield widget


def _page_is_one_editor(widget: HunkDiffWidget) -> bool:
    editor = widget._container.findChildren(QPlainTextEdit)[0]
    return widget._hscroll.pageStep() == editor.viewport().width()


@pytest.mark.parametrize("view", ["all files", "one file"])
def test_expanding_a_block_collapsed_through_a_resize_pages_by_one_editor(
    qtbot, side_by_side, pane, view
):
    """A resize while every block is collapsed measures no visible editor, so
    the bar falls back to the pane's width: two editors' worth, side by side.
    Expanding has to measure again, or each page skips half of every line."""
    if view == "one file":
        pane.load_file("long.txt")
    else:
        pane.load_all_files(["long.txt"])
    qtbot.waitUntil(lambda: bool(pane._container.findChildren(QPlainTextEdit)))
    qtbot.waitUntil(lambda: pane._hscroll.isVisible() and _page_is_one_editor(pane))
    toggle = pane._container.findChild(_CollapseToggle)
    wide = pane._container.width()

    toggle.click()
    pane.resize(800, 600)
    qtbot.waitUntil(lambda: pane._container.width() < wide)
    toggle.click()

    qtbot.waitUntil(lambda: _page_is_one_editor(pane), timeout=2000)
