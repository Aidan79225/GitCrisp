"""Reloading the working-tree all-files view keeps the user's place.

Every stage, unstage or discard reloads the view, which starts again from
skeletons far shorter than the blocks they stand for. Unless each one keeps
its block's height until realised, the unchanged scroll value lands files
further down, and the file the user just staged a hunk in jumps off screen.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QPlainTextEdit

from git_gui.domain.entities import Hunk, LineKind, StagingState
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget

PATHS = [f"f{i}.txt" for i in range(30)]
HUNK = Hunk(
    header="@@ -1,18 +1,18 @@",
    lines=[(LineKind.ADDED, f"line {i}\n") for i in range(18)],
)


@pytest.fixture
def widget(qtbot):
    """A shown all-files pane, torn down only after its redraws have settled.

    A reload leaves the old blocks to deleteLater, and destroying their
    editors queues a scrollbar re-measure; it has to run while the pane still
    exists, so the pane is not handed to qtbot, which would destroy it first.
    """
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    queries.get_working_tree_diff_map.execute.return_value = {
        path: {StagingState.UNSTAGED: [HUNK]} for path in PATHS
    }
    w = HunkDiffWidget(queries, MagicMock())
    w.resize(800, 500)
    w.show()
    yield w
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qtbot.wait(10)
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _frames(widget: HunkDiffWidget) -> dict:
    return {path: frame for path, frame, _inner, _skeleton in widget._loader._block_refs}


def _is_realised(widget: HunkDiffWidget, path: str) -> bool:
    return bool(_frames(widget)[path].findChildren(QPlainTextEdit))


def _block_at_top(widget: HunkDiffWidget) -> str | None:
    top = widget._scroll.verticalScrollBar().value()
    frames = _frames(widget).items()
    return next((path for path, frame in frames if frame.geometry().bottom() >= top), None)


def _top_block_is_realised(widget: HunkDiffWidget) -> bool:
    path = _block_at_top(widget)
    return path is not None and _is_realised(widget, path)


def _wait_for_the_content_to_fit(widget: HunkDiffWidget, qtbot) -> None:
    """Wait until the scroll content is as tall as the blocks it holds.

    Showing a built block's hunks lays the content out again at once, but in
    the content's old height, which squeezes the blocks built before it; the
    scroll area resizes the content to fit on the next event-loop turn. A
    position read in between is wrong, and a reload started in between
    leaves that resize to land on the emptied pane, where it drops the
    scroll value to zero.
    """
    content = widget._scroll.widget()
    qtbot.waitUntil(lambda: content.height() >= content.sizeHint().height(), timeout=2000)


def _top_block(widget: HunkDiffWidget, qtbot) -> str | None:
    _wait_for_the_content_to_fit(widget, qtbot)
    return _block_at_top(widget)


def _scroll_down_to(widget: HunkDiffWidget, qtbot, target: str) -> None:
    """Scroll block by block, realising each on the way, as a user would."""
    bar = widget._scroll.verticalScrollBar()
    for path in PATHS[: PATHS.index(target) + 1]:
        _wait_for_the_content_to_fit(widget, qtbot)
        bar.setValue(_frames(widget)[path].y())
        qtbot.waitUntil(lambda p=path: _is_realised(widget, p), timeout=2000)
    _wait_for_the_content_to_fit(widget, qtbot)
    bar.setValue(_frames(widget)[target].y())
    qtbot.wait(100)  # the loader's scroll timer is due: let it build what it will
    _wait_for_the_content_to_fit(widget, qtbot)


def test_a_reload_keeps_the_same_file_at_the_top(widget, qtbot):
    widget.load_all_files(PATHS)
    qtbot.waitUntil(lambda: _is_realised(widget, "f0.txt"), timeout=2000)
    _scroll_down_to(widget, qtbot, "f15.txt")
    assert _top_block(widget, qtbot) == "f15.txt"

    widget.load_all_files(PATHS)
    qtbot.waitUntil(lambda: _top_block_is_realised(widget), timeout=2000)

    assert _top_block(widget, qtbot) == "f15.txt"


def test_ticking_a_hunk_leaves_the_reload_to_the_owner(widget, qtbot):
    """The owner reloads on hunk_toggled with the new list of changed files;
    reloading here as well rebuilt every block and queried every diff twice."""
    widget.load_all_files(PATHS)
    qtbot.waitUntil(lambda: _is_realised(widget, "f0.txt"), timeout=2000)
    diff_map_query = widget._queries.get_working_tree_diff_map.execute

    with qtbot.waitSignal(widget.hunk_toggled, timeout=1000):
        _frames(widget)["f0.txt"].findChild(QCheckBox).click()
    qtbot.wait(100)  # time for a stray reload's worker to query

    assert diff_map_query.call_count == 1
