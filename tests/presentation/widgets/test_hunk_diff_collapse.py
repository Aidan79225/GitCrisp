"""Collapsing a file block in the working-tree all-files view.

The view realises blocks lazily, as they scroll into sight, so a collapse has
to cooperate with that: it can reveal skeletons below it, and it can happen
before the block's diff has even arrived.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QPlainTextEdit

from git_gui.domain.entities import Hunk, LineKind, StagingState
from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget


def _hunk(lines: int) -> Hunk:
    return Hunk(
        header=f"@@ -1,{lines} +1,{lines} @@",
        lines=[(LineKind.ADDED, f"line {i}\n") for i in range(lines)],
    )


class _GatedQueries:
    """A query bus whose diff map arrives only once the test releases it."""

    def __init__(self, diff_map: dict) -> None:
        self.released = threading.Event()
        self._diff_map = diff_map
        self.get_working_tree_diff_map = MagicMock()
        self.get_working_tree_diff_map.execute.side_effect = self._wait_for_release
        self.list_submodules = MagicMock()
        self.list_submodules.execute.return_value = []

    def _wait_for_release(self, _paths):
        self.released.wait(5)
        return self._diff_map


@pytest.fixture
def make_widget(qtbot):
    """Build a shown pane over a gated query bus; no gate outlives its test."""
    gates: list[_GatedQueries] = []

    def make(diff_map: dict) -> tuple[HunkDiffWidget, _GatedQueries]:
        queries = _GatedQueries(diff_map)
        gates.append(queries)
        widget = HunkDiffWidget(queries, MagicMock())
        qtbot.addWidget(widget)
        widget.resize(800, 500)
        widget.show()
        return widget, queries

    yield make
    for gate in gates:
        gate.released.set()


def _frame_of(widget: HunkDiffWidget, path: str):
    return next(frame for p, frame, _inner, _sk in widget._loader._block_refs if p == path)


def _editors(frame) -> list[QPlainTextEdit]:
    return frame.findChildren(QPlainTextEdit)


def test_collapsing_a_block_realises_the_blocks_it_reveals(qtbot, make_widget):
    """Collapsing a tall first file shrinks the content without moving the
    scroll bar, so nothing but the collapse itself can tell the loader that
    the next files are now on screen."""
    paths = [f"f{i}.txt" for i in range(8)]
    diff_map = {p: {StagingState.UNSTAGED: [_hunk(60 if p == "f0.txt" else 3)]} for p in paths}
    widget, queries = make_widget(diff_map)
    queries.released.set()
    widget.load_all_files(paths)
    qtbot.waitUntil(lambda: bool(_editors(_frame_of(widget, "f0.txt"))), timeout=2000)
    built_before = _wait_until_the_loader_is_idle(qtbot, widget)
    assert built_before < len(paths), "the tall first file pushes some block below the fold"

    _frame_of(widget, "f0.txt").findChild(_CollapseToggle).click()

    # Which block the collapse uncovers depends on the machine's font and
    # layout; that it uncovers one does not.
    qtbot.waitUntil(lambda: len(widget._loader._realized) > built_before, timeout=2000)


def _wait_until_the_loader_is_idle(qtbot, widget: HunkDiffWidget) -> int:
    """Return how many blocks are built once no more have been for a while.

    The loader builds one block per event-loop turn while the first block is
    still growing, so a fixed wait can end in the middle of that; the fold is
    only meaningful once it has stopped.
    """
    built = -1
    for _ in range(30):
        qtbot.wait(100)
        now = len(widget._loader._realized)
        if now == built:
            return now
        built = now
    raise AssertionError("the loader never settled")


def test_a_block_collapsed_before_its_diff_arrives_stays_collapsed(qtbot, make_widget):
    """The chevron says collapsed, so hunks that arrive later must not show;
    otherwise the next click "expands" a block that is already open."""
    widget, queries = make_widget({"x.txt": {StagingState.UNSTAGED: [_hunk(3)]}})
    widget.load_all_files(["x.txt"])
    frame = _frame_of(widget, "x.txt")
    toggle = frame.findChild(_CollapseToggle)

    toggle.click()
    queries.released.set()
    qtbot.waitUntil(lambda: bool(_editors(frame)), timeout=2000)

    assert not toggle.is_expanded()
    assert not any(editor.isVisible() for editor in _editors(frame))
