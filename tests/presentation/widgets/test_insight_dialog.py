"""Git Insight: closing it, the date ranges it asks for, and what it shows."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QDate, Qt, QTimer
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


# ── Date ranges ─────────────────────────────────────────────────────────────
_WEDNESDAY = date(2026, 10, 21)


def _no_history() -> MagicMock:
    queries = MagicMock()
    queries.get_commit_stats.execute.return_value = []
    return queries


def _range(window, label: str, today: date = _WEDNESDAY):
    dialog = InsightDialog(_no_history(), window, today=lambda: today)
    return dialog._compute_range(label)


def _on_the_users_clock(moment: datetime) -> datetime:
    return moment.astimezone().replace(tzinfo=None)


def test_this_week_starts_at_local_midnight_on_monday(window):
    since, until = _range(window, "This Week")

    assert _on_the_users_clock(since) == datetime(2026, 10, 19)
    assert until is None


def test_on_monday_this_week_starts_that_morning(window):
    """Early on Monday local time it is still Sunday in UTC; the week is the new one."""
    since, _until = _range(window, "This Week", today=date(2026, 10, 19))

    assert _on_the_users_clock(since) == datetime(2026, 10, 19)


def test_this_month_starts_at_local_midnight_on_the_first(window):
    since, _until = _range(window, "This Month")

    assert _on_the_users_clock(since) == datetime(2026, 10, 1)


def test_this_year_starts_at_local_midnight_on_new_years_day(window):
    since, _until = _range(window, "This Year")

    assert _on_the_users_clock(since) == datetime(2026, 1, 1)


def test_a_custom_range_covers_whole_local_days(window):
    dialog = InsightDialog(_no_history(), window)
    dialog._start_date.setDate(QDate(2026, 10, 18))
    dialog._end_date.setDate(QDate(2026, 10, 18))

    since, until = dialog._compute_range("Custom")

    assert _on_the_users_clock(since) == datetime(2026, 10, 18)
    assert _on_the_users_clock(until) == datetime(2026, 10, 18, 23, 59, 59)
