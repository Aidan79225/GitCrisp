"""The working-tree file list is wired to the delegate that paints its own boxes."""

from __future__ import annotations

from unittest.mock import MagicMock

from git_gui.presentation.widgets.check_indicator import CheckIndicatorDelegate
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


def test_file_list_uses_the_check_indicator_delegate(qtbot):
    widget = WorkingTreeWidget(MagicMock(), MagicMock())
    qtbot.addWidget(widget)
    assert isinstance(widget._file_view.itemDelegate(), CheckIndicatorDelegate)
