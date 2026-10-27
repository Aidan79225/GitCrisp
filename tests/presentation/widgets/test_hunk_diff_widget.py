"""Integration tests for HunkDiffWidget lazy loading flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from git_gui.domain.entities import Hunk
from git_gui.presentation.widgets.diff_block import SyntaxFormats
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget


class FakeQueryBus:
    """Minimal stand-in that satisfies HunkDiffWidget.__init__ and load methods."""

    def __init__(self):
        # Real return types, not mocks: the pane's workers emit these through
        # typed Qt signals, and a MagicMock in a list-typed signal argument
        # cannot be converted, which crashes the interpreter once the queued
        # delivery runs, often in a later test.
        self.get_working_tree_diff_map = MagicMock()
        self.get_working_tree_diff_map.execute.return_value = {}
        self.get_staged_diff = MagicMock()
        self.get_staged_diff.execute.return_value = []
        self.get_file_diff = MagicMock()
        self.get_file_diff.execute.return_value = []
        self.list_submodules = MagicMock()
        self.list_submodules.execute.return_value = []


@pytest.fixture
def widget(qtbot):
    queries = FakeQueryBus()
    commands = MagicMock()
    w = HunkDiffWidget(queries, commands)
    qtbot.addWidget(w)
    w.show()
    return w


def test_load_all_files_creates_skeleton_blocks(widget):
    """Skeleton blocks are created synchronously before the bg thread runs."""
    widget.load_all_files(["a.txt", "b.txt"])

    assert widget._loader is not None
    assert len(widget._loader._block_refs) == 2
    paths = [ref[0] for ref in widget._loader._block_refs]
    assert paths == ["a.txt", "b.txt"]


def test_load_all_files_empty_clears_layout(widget):
    """Passing an empty list should clear the layout entirely."""
    # First load some files so there's content
    widget.load_all_files(["x.txt"])
    assert widget._loader._block_refs != []

    # Now load empty
    widget.load_all_files([])
    assert widget._layout.count() == 0
    assert widget._loader._block_refs == []


def test_clear_resets_loader(widget):
    """clear() should empty loader block refs."""
    widget.load_all_files(["a.txt", "b.txt", "c.txt"])
    assert len(widget._loader._block_refs) == 3

    widget.clear()
    assert widget._loader._block_refs == []
    assert widget._current_path is None
    assert widget._all_paths is None


def test_load_file_switches_to_single_mode(widget):
    """load_file sets single-file mode state."""
    widget.load_file("a.txt")

    assert widget._current_path == "a.txt"
    assert widget._all_paths is None


def test_load_all_files_caps_number_of_blocks(widget):
    """A huge working tree only builds up to MAX_AGGREGATE_FILE_BLOCKS blocks."""
    from git_gui.presentation.widgets.diff_block import MAX_AGGREGATE_FILE_BLOCKS

    paths = [f"f{i}.txt" for i in range(MAX_AGGREGATE_FILE_BLOCKS + 50)]
    widget.load_all_files(paths)

    # Only the capped subset gets lazy diff blocks…
    assert len(widget._loader._block_refs) == MAX_AGGREGATE_FILE_BLOCKS
    shown = [ref[0] for ref in widget._loader._block_refs]
    assert shown == paths[:MAX_AGGREGATE_FILE_BLOCKS]
    # …but every path is still remembered for single-file selection.
    assert widget._all_paths == paths


def test_load_all_files_only_fetches_shown_paths(widget):
    """The diff-map query is asked only for the paths actually rendered."""
    from git_gui.presentation.widgets.diff_block import MAX_AGGREGATE_FILE_BLOCKS

    paths = [f"f{i}.txt" for i in range(MAX_AGGREGATE_FILE_BLOCKS + 10)]
    widget.load_all_files(paths)

    # Give the daemon worker thread a moment to invoke the query.
    import time

    for _ in range(50):
        if widget._queries.get_working_tree_diff_map.execute.called:
            break
        time.sleep(0.01)

    widget._queries.get_working_tree_diff_map.execute.assert_called_once()
    (called_paths,) = widget._queries.get_working_tree_diff_map.execute.call_args.args
    assert called_paths == paths[:MAX_AGGREGATE_FILE_BLOCKS]


def test_widget_builds_syntax_formats(widget):
    """The working-tree view carries syntax formats so its diffs get the same
    Pygments colouring as the commit-detail view."""
    assert isinstance(widget._syntax_formats, SyntaxFormats)


def test_add_hunk_block_passes_syntax_formats_and_filename(widget):
    """Regression: the working-tree diff must forward syntax_formats + filename
    to the hunk builder, otherwise hunks render with no syntax highlighting."""
    hunk = Hunk(header="@@ -1,1 +1,1 @@", lines=[("+", "def foo(): pass\n")])
    with patch("git_gui.presentation.widgets.hunk_diff.add_hunk_view") as add_widget:
        widget._add_hunk_block(hunk, is_staged=False, path="foo.py", parent_layout=widget._layout)
    kwargs = add_widget.call_args.kwargs
    assert kwargs["syntax_formats"] is widget._syntax_formats
    assert kwargs["filename"] == "foo.py"


def test_theme_change_rebuilds_syntax_formats(widget):
    """A theme switch must refresh the cached formats so blocks realised
    afterwards use the new palette."""
    before = widget._syntax_formats
    widget._on_theme_changed()
    assert isinstance(widget._syntax_formats, SyntaxFormats)
    assert widget._syntax_formats is not before


def test_files_beyond_the_cap_get_the_commit_views_notice(widget):
    """Both panes cap their blocks; one notice keeps their wording in step."""
    from PySide6.QtWidgets import QLabel

    from git_gui.presentation.widgets.diff_block import (
        MAX_AGGREGATE_FILE_BLOCKS,
        make_overflow_notice,
    )

    widget.load_all_files([f"f{i}.txt" for i in range(MAX_AGGREGATE_FILE_BLOCKS + 3)])

    expected = make_overflow_notice(3).text()
    labels = widget._container.findChildren(QLabel)
    assert [label.text() for label in labels if label.text() == expected] == [expected]


def test_a_submodules_file_and_hunk_headers_both_open_it(qtbot):
    from types import SimpleNamespace

    from PySide6.QtCore import Qt

    from git_gui.domain.entities import LineKind
    from git_gui.presentation.widgets.diff_block import _ClickableLabel
    from tests.presentation.widgets.hunk_diff_helpers import workers_joined_on_exit

    queries = FakeQueryBus()
    queries.list_submodules.execute.return_value = [SimpleNamespace(path="libs/core")]
    queries.get_file_diff.execute.return_value = [
        Hunk(header="@@ -1 +1 @@", lines=[(LineKind.ADDED, "Subproject commit 1234\n")])
    ]
    with workers_joined_on_exit():
        widget = HunkDiffWidget(queries, MagicMock())
        qtbot.addWidget(widget)
        widget.load_file("libs/core")
        qtbot.waitUntil(lambda: len(widget._container.findChildren(_ClickableLabel)) == 2)
    opened: list[str] = []
    widget.submodule_open_requested.connect(opened.append)

    for header in widget._container.findChildren(_ClickableLabel):
        qtbot.mouseClick(header, Qt.LeftButton)

    assert opened == ["libs/core", "libs/core"]
