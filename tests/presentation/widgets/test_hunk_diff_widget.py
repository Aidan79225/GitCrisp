"""Integration tests for HunkDiffWidget lazy loading flow."""
from __future__ import annotations
from unittest.mock import MagicMock

import pytest

from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget


class FakeQueryBus:
    """Minimal stand-in that satisfies HunkDiffWidget.__init__ and load methods."""

    def __init__(self):
        self.get_working_tree_diff_map = MagicMock()
        self.get_staged_diff = MagicMock()
        self.get_file_diff = MagicMock()
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
