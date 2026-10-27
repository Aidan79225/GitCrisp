"""Collapsing and expanding a file block in the commit view."""

from __future__ import annotations

import threading
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QPlainTextEdit

from git_gui.domain.entities import Commit, FileStatus, Hunk, LineKind
from git_gui.presentation.app_settings import set_side_by_side_diff
from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle
from git_gui.presentation.widgets.diff import DiffWidget
from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit

_HUNK = Hunk(header="@@ -1,3 +1,3 @@", lines=[(LineKind.ADDED, f"line {i}\n") for i in range(3)])


def _queries_with_gated_diffs(released: threading.Event) -> MagicMock:
    """A query bus for one commit whose diffs arrive only once `released` is set."""
    queries = MagicMock()
    queries.get_commit_detail.execute.return_value = Commit(
        oid="abc123", message="Subject\n", author="A", timestamp=datetime(2025, 1, 1), parents=[]
    )
    queries.get_branches.execute.return_value = []
    queries.get_commit_files.execute.return_value = [
        FileStatus(path="x.txt", status="staged", delta="modified")
    ]
    queries.list_submodules.execute.return_value = []

    def diffs_once_released(_oid: str) -> dict:
        released.wait(5)
        return {"x.txt": [_HUNK]}

    queries.get_commit_diff_map.execute.side_effect = diffs_once_released
    return queries


@pytest.fixture
def gated(qtbot):
    """A shown commit view and the gate holding back its diffs; no gate outlives its test."""
    released = threading.Event()
    widget = DiffWidget(_queries_with_gated_diffs(released), MagicMock())
    qtbot.addWidget(widget)
    widget.resize(800, 500)
    widget.show()
    yield widget, released
    released.set()


def test_a_commit_file_collapsed_before_its_diff_arrives_stays_collapsed(qtbot, gated):
    """The chevron says collapsed, so hunks that arrive later must not show."""
    widget, released = gated
    widget.load_commit("abc123")
    frame = widget._loader._block_refs[0][1]
    toggle = frame.findChild(_CollapseToggle)

    toggle.click()
    released.set()
    qtbot.waitUntil(lambda: bool(frame.findChildren(QPlainTextEdit)), timeout=2000)

    assert not toggle.is_expanded()
    assert not any(editor.isVisible() for editor in frame.findChildren(QPlainTextEdit))


# ── The shared horizontal bar after a collapsed block is expanded ────────────

_LONG_HUNK = Hunk(
    header="@@ -1,1 +1,1 @@",
    lines=[(LineKind.REMOVED, "y" * 600 + "\n"), (LineKind.ADDED, "x" * 600 + "\n")],
)


@pytest.fixture
def side_by_side():
    """Two editors share each row, so a page of the whole pane is two pages."""
    set_side_by_side_diff(True)
    yield
    set_side_by_side_diff(False)


def _long_commit_queries() -> MagicMock:
    """A query bus for one commit changing one file with a line far wider than the pane."""
    queries = MagicMock()
    queries.get_commit_detail.execute.return_value = Commit(
        oid="abc123", message="Subject\n", author="A", timestamp=datetime(2025, 1, 1), parents=[]
    )
    queries.get_branches.execute.return_value = []
    queries.get_commit_files.execute.return_value = [
        FileStatus(path="long.txt", status="staged", delta="modified")
    ]
    queries.list_submodules.execute.return_value = []
    queries.get_commit_diff_map.execute.return_value = {"long.txt": [_LONG_HUNK]}
    queries.get_file_diff.execute.return_value = [_LONG_HUNK]
    return queries


@pytest.fixture
def long_commit(qtbot):
    """A shown commit view holding that commit, its diff fetch let finish before teardown."""
    with workers_joined_on_exit():
        widget = DiffWidget(_long_commit_queries(), MagicMock())
        qtbot.addWidget(widget)
        widget.resize(900, 600)
        widget.show()
        widget.load_commit("abc123")
        yield widget


def _select_the_file(widget: DiffWidget) -> None:
    widget._file_navigator._list_view.setCurrentIndex(widget._diff_model.index(0))


def _first_editor(widget: DiffWidget) -> QPlainTextEdit:
    return widget._diff_container.findChildren(QPlainTextEdit)[0]


def _page_is_one_editor(widget: DiffWidget) -> bool:
    return widget._hscroll.pageStep() == _first_editor(widget).viewport().width()


@pytest.mark.parametrize("view", ["all files", "one file"])
def test_expanding_a_block_collapsed_through_a_resize_pages_by_one_editor(
    qtbot, side_by_side, long_commit, view
):
    """A resize while every block is collapsed measures no visible editor, so
    the bar falls back to the pane's width: two editors' worth, side by side.
    Expanding has to measure again, or each page skips half of every line."""
    widget = long_commit
    if view == "one file":
        _select_the_file(widget)
    qtbot.waitUntil(lambda: bool(widget._diff_container.findChildren(QPlainTextEdit)))
    qtbot.waitUntil(lambda: widget._hscroll.isVisible() and _page_is_one_editor(widget))
    toggle = widget._diff_container.findChild(_CollapseToggle)
    wide = widget._diff_container.width()

    toggle.click()
    widget.resize(800, 600)
    qtbot.waitUntil(lambda: widget._diff_container.width() < wide)
    toggle.click()

    qtbot.waitUntil(lambda: _page_is_one_editor(widget), timeout=2000)
