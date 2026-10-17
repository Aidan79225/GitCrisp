"""The working-tree pane's shared horizontal bar follows the file on screen."""

from __future__ import annotations

from unittest.mock import MagicMock

from git_gui.domain.entities import Hunk, LineKind
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget

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
