"""Git Insight: closing it, the date ranges it asks for, and what it shows."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from git_gui.presentation.widgets.insight_dialog import InsightDialog


class _EndlessHistory:
    """A history walk that keeps going until it is cancelled (or 10 s pass)."""

    def __init__(self) -> None:
        self.stopped_by_cancel = threading.Event()

    def execute(self, since, until, *, cancel):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if cancel():
                self.stopped_by_cancel.set()
                return
            time.sleep(0.01)
            yield from ()


def _queries_walking(history) -> MagicMock:
    queries = MagicMock()
    queries.get_commit_stats = history
    return queries


def _shown_dialog(qtbot, queries) -> InsightDialog:
    dialog = InsightDialog(queries)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    return dialog


def test_esc_stops_the_history_walk(qtbot):
    history = _EndlessHistory()
    dialog = _shown_dialog(qtbot, _queries_walking(history))

    QTest.keyClick(dialog, Qt.Key_Escape)

    assert history.stopped_by_cancel.wait(2)


def test_closing_the_window_stops_the_history_walk(qtbot):
    history = _EndlessHistory()
    dialog = _shown_dialog(qtbot, _queries_walking(history))

    dialog.close()

    assert history.stopped_by_cancel.wait(2)
