"""The commit pane's shared horizontal bar does not outlive the pane."""

from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from git_gui.presentation.widgets.diff import DiffWidget


def test_a_re_measure_still_pending_when_the_pane_is_destroyed_is_dropped(qtbot):
    """Otherwise it reaches into the destroyed container and raises."""
    queries = MagicMock()
    queries.list_submodules.execute.return_value = []
    widget = DiffWidget(queries, MagicMock())
    widget.set_buses(queries, MagicMock())  # clears the blocks, queuing a re-measure

    widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qtbot.wait(20)
