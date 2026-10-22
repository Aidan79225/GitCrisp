"""Each hunk's stage checkbox in the working-tree pane carries a spoken name.

The checkbox has no text of its own, so without a name a screen reader
announces only "check box, checked" for every hunk, and staging by hunk
cannot be done by ear; the discard button beside it is already named.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QCheckBox, QVBoxLayout, QWidget

from git_gui.domain.entities import Hunk, LineKind
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget

HUNK = Hunk(header="@@ -8,6 +8,7 @@", lines=[(LineKind.ADDED, "a\n")])


def _spoken_name(widget) -> str:
    return QAccessible.queryAccessibleInterface(widget).text(QAccessible.Name)


def test_a_hunks_stage_checkbox_is_named_by_its_hunk(qtbot):
    widget = HunkDiffWidget(MagicMock(), MagicMock())
    qtbot.addWidget(widget)
    host = QWidget()
    qtbot.addWidget(host)

    widget._add_hunk_block(HUNK, is_staged=False, path="a.txt", parent_layout=QVBoxLayout(host))

    assert _spoken_name(host.findChild(QCheckBox)) == "Stage hunk @@ -8,6 +8,7 @@"
