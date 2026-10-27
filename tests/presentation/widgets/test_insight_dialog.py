"""Git Insight: closing it, the date ranges it asks for, and what it shows."""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from git_gui.domain.entities import CommitStat, FileStat
from git_gui.presentation.widgets.insight_dialog import (
    InsightDialog,
    InsightRange,
    _AuthorRow,
    _FileRow,
)


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


def _range(window, chosen: InsightRange, today: date = _WEDNESDAY):
    dialog = InsightDialog(_no_history(), window, today=lambda: today)
    return dialog._compute_range(chosen)


def _on_the_users_clock(moment: datetime) -> datetime:
    return moment.astimezone().replace(tzinfo=None)


def test_this_week_starts_at_local_midnight_on_monday(window):
    since, until = _range(window, InsightRange.THIS_WEEK)

    assert _on_the_users_clock(since) == datetime(2026, 10, 19)
    assert until is None


def test_on_monday_this_week_starts_that_morning(window):
    """Early on Monday local time it is still Sunday in UTC; the week is the new one."""
    since, _until = _range(window, InsightRange.THIS_WEEK, today=date(2026, 10, 19))

    assert _on_the_users_clock(since) == datetime(2026, 10, 19)


def test_this_month_starts_at_local_midnight_on_the_first(window):
    since, _until = _range(window, InsightRange.THIS_MONTH)

    assert _on_the_users_clock(since) == datetime(2026, 10, 1)


def test_this_year_starts_at_local_midnight_on_new_years_day(window):
    since, _until = _range(window, InsightRange.THIS_YEAR)

    assert _on_the_users_clock(since) == datetime(2026, 1, 1)


def test_a_custom_range_covers_whole_local_days(window):
    dialog = InsightDialog(_no_history(), window)
    dialog._start_date.setDate(QDate(2026, 10, 18))
    dialog._end_date.setDate(QDate(2026, 10, 18))

    since, until = dialog._compute_range(InsightRange.CUSTOM)

    assert _on_the_users_clock(since) == datetime(2026, 10, 18)
    assert _on_the_users_clock(until) == datetime(2026, 10, 18, 23, 59, 59)


# ── What it shows ───────────────────────────────────────────────────────────
_ALICE = "Alice <alice@example.com>"
_BOB = "Bob <bob@example.com>"


def _commit(oid: str, author: str, *files: tuple[str, int, int]) -> CommitStat:
    return CommitStat(
        oid=oid,
        author=author,
        timestamp=datetime(2026, 10, 1, tzinfo=UTC),
        files=[FileStat(path, added, deleted) for path, added, deleted in files],
    )


_HISTORY = [
    _commit("c1", _ALICE, ("app.py", 10, 2), ("README.md", 1, 0)),
    _commit("c2", _ALICE, ("app.py", 5, 5)),
    _commit("c3", _BOB, ("lib.py", 0, 7)),
]


def _loaded_dialog(qtbot, window, history) -> InsightDialog:
    queries = MagicMock()
    queries.get_commit_stats.execute.side_effect = lambda since, until, cancel: iter(history)
    dialog = InsightDialog(queries, window)
    qtbot.waitUntil(lambda: dialog._last_render is not None)
    return dialog


def test_each_author_is_credited_with_their_commits(qtbot, window):
    commits, _added, _deleted, _files, _changed, total = _loaded_dialog(
        qtbot, window, _HISTORY
    )._last_render

    assert commits == {_ALICE: 2, _BOB: 1}
    assert total == 3


def test_each_author_is_credited_with_the_lines_they_added_and_deleted(qtbot, window):
    _commits, added, deleted, _files, _changed, _total = _loaded_dialog(
        qtbot, window, _HISTORY
    )._last_render

    assert added == {_ALICE: 16, _BOB: 0}
    assert deleted == {_ALICE: 7, _BOB: 7}


def test_a_file_counts_once_per_commit_that_changes_it(qtbot, window):
    _commits, _added, _deleted, file_counts, changed, _total = _loaded_dialog(
        qtbot, window, _HISTORY
    )._last_render

    assert file_counts == {"app.py": 2, "README.md": 1, "lib.py": 1}
    assert changed == {"app.py", "README.md", "lib.py"}


def test_a_superseded_load_that_finishes_late_is_not_shown(qtbot, window):
    dialog = _loaded_dialog(qtbot, window, _HISTORY)
    shown = dialog._last_render

    dialog._on_loaded(dialog._load_generation - 1, {"Mallory": 99}, {}, {}, {}, set(), 99)

    assert dialog._last_render is shown


def test_a_superseded_load_that_fails_late_does_not_hide_the_results(qtbot, window):
    dialog = _loaded_dialog(qtbot, window, _HISTORY)

    dialog._on_failed(dialog._load_generation - 1, "boom")

    assert not dialog._scroll.isHidden()


def test_authors_are_ranked_by_commit_count(qtbot, window):
    dialog = _loaded_dialog(qtbot, window, [*reversed(_HISTORY)])

    rows = dialog._content.findChildren(_AuthorRow)

    assert [row._name for row in rows] == [_ALICE, _BOB]


def test_only_the_ten_most_modified_files_are_listed(qtbot, window):
    many_files = [_commit(f"c{n}", _ALICE, (f"file{n}.py", 1, 0)) for n in range(12)]
    dialog = _loaded_dialog(qtbot, window, many_files)

    assert len(dialog._content.findChildren(_FileRow)) == 10


def test_the_result_rows_paint(qtbot, window):
    dialog = _loaded_dialog(qtbot, window, _HISTORY)

    assert not dialog.grab().isNull()


# ── Custom range edges ──────────────────────────────────────────────────────
def _custom_range(window, start: QDate, end: QDate):
    dialog = InsightDialog(_no_history(), window)
    dialog._start_date.setDate(start)
    dialog._end_date.setDate(end)
    return dialog._compute_range(InsightRange.CUSTOM)


def test_a_custom_range_starts_no_earlier_than_the_clock_can_convert(window):
    """Windows' localtime() rejects a time before the epoch, and astimezone()
    probes a day either side of the time it converts."""
    since, _until = _custom_range(window, QDate(1752, 9, 14), QDate(2026, 10, 18))

    assert _on_the_users_clock(since) == datetime(1970, 1, 3)


def test_a_custom_end_before_the_epoch_ends_on_the_first_day_the_clock_can_convert(window):
    _since, until = _custom_range(window, QDate(1960, 1, 1), QDate(1969, 12, 31))

    assert _on_the_users_clock(until) == datetime(1970, 1, 3, 23, 59, 59)


def test_a_custom_start_past_2099_stops_at_the_last_day_git_can_read(window):
    """git's date parser stops at 2099 and ignores a later --since, so a range
    starting in 2100 counted the whole history."""
    since, _until = _custom_range(window, QDate(2100, 1, 1), QDate(9999, 12, 31))

    assert _on_the_users_clock(since) == datetime(2099, 12, 30)


def test_a_custom_range_ends_no_later_than_git_can_read(window):
    """An --until past 2099 matches no commit at all."""
    _since, until = _custom_range(window, QDate(2026, 10, 18), QDate(9999, 12, 31))

    assert _on_the_users_clock(until) == datetime(2099, 12, 30, 23, 59, 59)


def test_moving_the_custom_end_before_the_epoch_counts_the_new_range(window):
    """Converting the end raised inside the date slot, so no walk started and
    the dialog kept the previous range's totals under the new dates."""
    walks: list = []
    dialog = InsightDialog(_no_history(), window, run_in_background=walks.append)
    QTest.mouseClick(dialog._range_buttons[InsightRange.CUSTOM], Qt.LeftButton)
    walks.clear()

    dialog._end_date.setDate(QDate(1969, 12, 31))

    assert len(walks) == 1


# ── Range buttons ───────────────────────────────────────────────────────────
def test_the_dialog_opens_on_this_month(window):
    dialog = InsightDialog(_no_history(), window)

    assert dialog._range_group.checkedButton().text() == InsightRange.THIS_MONTH.label


def test_choosing_custom_shows_the_date_pickers(qtbot, window):
    dialog = _shown_dialog(qtbot, window, _no_history())

    QTest.mouseClick(dialog._range_buttons[InsightRange.CUSTOM], Qt.LeftButton)

    assert dialog._custom_widget.isVisible()


# ── Background walk ─────────────────────────────────────────────────────────
def test_a_walk_superseded_by_a_new_range_is_not_shown(qtbot, window):
    held: list = []
    queries = MagicMock()
    queries.get_commit_stats.execute.side_effect = lambda since, until, cancel: iter(_HISTORY)
    dialog = InsightDialog(queries, window, run_in_background=held.append)
    QTest.mouseClick(dialog._range_buttons[InsightRange.ALL], Qt.LeftButton)
    first_walk, current_walk = held

    current_walk()
    shown = dialog._last_render
    # Rendered, or `is shown` below would compare None with None.
    assert shown is not None and shown[-1] == len(_HISTORY)
    first_walk()

    assert dialog._last_render is shown
