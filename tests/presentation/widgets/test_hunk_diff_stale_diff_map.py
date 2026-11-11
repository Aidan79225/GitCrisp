"""A diff map still on its way when the all-files view moves on is dropped.

The view asks for its diffs off the UI thread. A repo switch rebuilds the
blocks before an older answer arrives; delivered anyway, it filled the new
blocks with the old repo's hunks, and since a block is realised only once,
the right diff never replaced them.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from PySide6.QtWidgets import QPlainTextEdit

from git_gui.domain.entities import Hunk, LineKind, StagingState
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget
from tests.presentation.widgets.hunk_diff_helpers import wait_until_deleted


def _gated_queries(line: str) -> tuple[MagicMock, threading.Event]:
    """A query bus whose README.md diff, adding *line*, waits for the gate."""
    released = threading.Event()
    hunk = Hunk(header="@@ -1,1 +1,1 @@", lines=[(LineKind.ADDED, f"{line}\n")])

    def _diff_map(_paths):
        released.wait(5)
        return {"README.md": {StagingState.UNSTAGED: [hunk]}}

    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    queries.get_working_tree_diff_map.execute.side_effect = _diff_map
    return queries, released


def _shown_text(widget: HunkDiffWidget) -> str:
    return "".join(e.toPlainText() for e in widget._container.findChildren(QPlainTextEdit))


def test_the_old_repos_diff_map_does_not_fill_the_new_repos_blocks(qtbot):
    old_queries, old_released = _gated_queries("from the old repo")
    new_queries, new_released = _gated_queries("from the new repo")
    widget = HunkDiffWidget(old_queries, MagicMock())
    qtbot.addWidget(widget)
    widget.resize(800, 500)
    widget.show()
    try:
        widget.load_all_files(["README.md"])
        old = widget._load_all_signals
        widget.set_buses(new_queries, MagicMock())
        widget.clear()
        widget.load_all_files(["README.md"])

        # The new worker waits until the old answer has been handled and its map is
        # seen to be dropped: a new answer landing first would replace a stale map
        # before it was shown, and the test would pass without the guard.
        old_released.set()
        wait_until_deleted(qtbot, old, timeout=5000)
        assert widget._loader._diff_map == {}
        new_released.set()
        qtbot.waitUntil(lambda: bool(_shown_text(widget)), timeout=2000)
    finally:
        old_released.set()
        new_released.set()

    assert "from the old repo" not in _shown_text(widget)
