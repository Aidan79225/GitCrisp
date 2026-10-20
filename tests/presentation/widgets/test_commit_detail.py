"""Tests for CommitDetailWidget — click-to-copy commit hash."""

from __future__ import annotations

from datetime import datetime

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from git_gui.domain.entities import Commit
from git_gui.presentation.widgets.commit_detail import CommitDetailWidget


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _disable_avatar_loader():
    """Disable the global avatar loader singleton for the duration of each
    test.

    CommitDetailWidget.set_commit() calls get_pixmap() which, on a cache
    miss, fires a QNetworkAccessManager request on the process-wide
    singleton AvatarLoader. That pending network reply can arrive while a
    later test is constructing or showing another widget, corrupting Qt's
    internal state and causing an access-violation crash on PySide6
    6.11 / Windows.

    Disabling the loader makes get_pixmap() return None immediately
    without touching the network, keeping the singleton clean between
    tests.
    """
    from git_gui.presentation.widgets.avatar_loader import get_avatar_loader

    loader = get_avatar_loader()
    original = loader._enabled
    loader._enabled = False
    yield
    loader._enabled = original


def _make_commit() -> Commit:
    return Commit(
        oid="a" * 40,
        message="msg",
        author="Alice <a@example.com>",
        timestamp=datetime(2026, 5, 6, 12, 0),
        parents=["b" * 40],
    )


def _send_click(widget: CommitDetailWidget, pos: QPoint) -> None:
    """Send a synthetic left-click press event directly to widget.

    Uses QApplication.sendEvent (synchronous dispatch to the widget's
    event handler) without going through the native OS event system. This
    avoids the PySide6 6.11/Windows crash where creating or destroying OS
    window handles (via widget.show() / qtbot teardown) corrupts Qt's
    internal handle table and segfaults subsequent tests.
    """
    pos_f = QPointF(pos)
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        pos_f,
        pos_f,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(widget, press)


def _shown(qtbot, refs: list[str] | None = None) -> CommitDetailWidget:
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 120)
    widget.set_commit(_make_commit(), refs or [])
    return widget


def _layout(widget: CommitDetailWidget):
    """Where the widget puts each part, as painting and clicks both see it."""
    return widget._layout(widget._commit, widget.fontMetrics())


def _copy_requests(widget: CommitDetailWidget) -> tuple[list[str], list[str]]:
    oids: list[str] = []
    refs: list[str] = []
    widget.commit_oid_copy_requested.connect(oids.append)
    widget.ref_copy_requested.connect(refs.append)
    return oids, refs


def test_a_click_before_any_commit_is_shown_copies_nothing(app, qtbot):
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 120)
    oids, refs = _copy_requests(widget)

    _send_click(widget, QPoint(200, 40))

    assert (oids, refs) == ([], [])


def test_clicking_oid_emits_copy_signal_with_full_oid(app, qtbot):
    widget = _shown(qtbot)
    oids, _ = _copy_requests(widget)

    _send_click(widget, _layout(widget).oid.center())

    assert oids == [_make_commit().oid]


def test_clicking_outside_oid_does_not_emit(app, qtbot):
    widget = _shown(qtbot)
    oids, _ = _copy_requests(widget)

    # Bottom-right corner is well outside the OID rect.
    _send_click(widget, widget.rect().bottomRight())

    assert oids == []


def test_after_clear_nothing_is_left_to_click(app, qtbot):
    widget = _shown(qtbot, ["main"])
    layout = _layout(widget)
    oids, refs = _copy_requests(widget)

    widget.clear()
    _send_click(widget, layout.oid.center())
    _send_click(widget, layout.badges[0].rect.center())

    assert (oids, refs) == ([], [])


def test_clicking_ref_badge_emits_copy_signal_with_bare_name(app, qtbot):
    """'tag:' and 'HEAD -> ' decorations are stripped from the copied text."""
    widget = _shown(qtbot, ["main", "tag:v1.2.0", "origin/feature"])
    _, refs = _copy_requests(widget)

    _send_click(widget, _layout(widget).badges[1].rect.center())

    assert refs == ["v1.2.0"]


def test_clicking_ref_badge_does_not_emit_oid_signal(app, qtbot):
    """A badge click must not also fire the OID copy signal."""
    widget = _shown(qtbot, ["main"])
    oids, refs = _copy_requests(widget)

    _send_click(widget, _layout(widget).badges[0].rect.center())

    assert refs == ["main"]
    assert oids == []


def test_the_badges_start_after_the_hash_without_overlapping_it(app, qtbot):
    widget = _shown(qtbot, ["main", "origin/feature"])
    layout = _layout(widget)

    first, second = (badge.rect for badge in layout.badges)

    assert not first.intersects(layout.oid)
    assert first.left() > layout.oid.right()
    assert second.left() > first.right()


# ── A long author in a narrow pane ───────────────────────────────────────────


LONG_AUTHOR = "dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>"


def _narrow_widget_with_long_author(qtbot) -> tuple[CommitDetailWidget, Commit]:
    """The diff pane beside blame or the reflog is about this narrow."""
    from dataclasses import replace

    widget = CommitDetailWidget()
    qtbot.addWidget(widget)
    widget.resize(444, 120)
    commit = replace(_make_commit(), author=LONG_AUTHOR)
    widget.set_commit(commit, [])
    return widget, commit


def test_a_long_author_ends_before_the_timestamp_starts(app, qtbot):
    """Painted in full, the author ran under the timestamp and both were unreadable."""
    widget, commit = _narrow_widget_with_long_author(qtbot)
    fm = widget.fontMetrics()

    line = widget._author_line(commit, fm)

    assert line.author != LONG_AUTHOR, "this width has to cut it"
    assert line.author_x + fm.horizontalAdvance(line.author) < line.timestamp_x


def test_a_cut_author_stays_whole_in_its_tooltip(app, qtbot):
    widget, _ = _narrow_widget_with_long_author(qtbot)
    layout = _layout(widget)
    line, y = layout.author_line, layout.author_top + 2

    assert widget._tooltip_at(QPoint(line.author_x + 5, y)) == LONG_AUTHOR
    assert widget._tooltip_at(QPoint(line.timestamp_x + 5, y)) == ""


def test_an_author_that_fits_gets_no_tooltip(app, qtbot):
    widget = _shown(qtbot)
    layout = _layout(widget)

    assert layout.cut_author is None
    assert widget._tooltip_at(QPoint(layout.author_line.author_x + 5, layout.author_top + 2)) == ""
