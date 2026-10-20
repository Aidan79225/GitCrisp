"""Git Insight: closing it, the date ranges it asks for, and what it shows."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

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


@pytest.fixture
def window(qtbot) -> QWidget:
    """Stands in for the main window. The dialog deletes itself on close, so
    it is parented here, as in the app, rather than handed to qtbot."""
    window = QWidget()
    qtbot.addWidget(window)
    return window


def _shown_dialog(qtbot, window, queries) -> InsightDialog:
    dialog = InsightDialog(queries, window)
    dialog.show()
    qtbot.waitExposed(dialog)
    return dialog


def test_esc_stops_the_history_walk(qtbot, window):
    history = _EndlessHistory()
    dialog = _shown_dialog(qtbot, window, _queries_walking(history))

    QTest.keyClick(dialog, Qt.Key_Escape)

    assert history.stopped_by_cancel.wait(2)


def test_closing_the_window_stops_the_history_walk(qtbot, window):
    history = _EndlessHistory()
    dialog = _shown_dialog(qtbot, window, _queries_walking(history))

    dialog.close()

    assert history.stopped_by_cancel.wait(2)


def test_a_closed_dialog_does_not_stay_behind_in_its_window(window):
    dialog = InsightDialog(_queries_walking(_EndlessHistory()), window)
    QTimer.singleShot(0, lambda: QTest.keyClick(dialog, Qt.Key_Escape))
    QTimer.singleShot(5000, dialog, dialog.reject)  # a failing test must not hang

    dialog.exec()

    assert window.findChildren(InsightDialog) == []
