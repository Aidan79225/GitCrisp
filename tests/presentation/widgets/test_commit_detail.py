"""Tests for CommitDetailWidget — click-to-copy commit hash."""

from __future__ import annotations

from datetime import datetime

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
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


def test_oid_rect_is_none_before_set_commit(app, qtbot):
    """Fresh widget has no _oid_rect before a commit is loaded."""
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)
    assert widget._oid_rect is None


def test_clicking_oid_emits_copy_signal_with_full_oid(app, qtbot):
    """Left-clicking within _oid_rect emits commit_oid_copy_requested.

    We seed _oid_rect directly (as paintEvent would after a real paint
    pass) because calling paintEvent on a hidden widget with QPainter(self)
    corrupts Qt-internal paint-device state on PySide6 6.11/Windows and
    causes crashes in subsequent tests that create native window handles.
    """
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 120)

    commit = _make_commit()
    widget.set_commit(commit, [])

    # Simulate what paintEvent would set after rendering the OID text.
    oid_rect = QRect(60, 30, 320, 18)
    widget._oid_rect = oid_rect

    received: list[str] = []
    widget.commit_oid_copy_requested.connect(received.append)

    _send_click(widget, oid_rect.center())

    assert received == [commit.oid]


def test_clicking_outside_oid_does_not_emit(app, qtbot):
    """Clicking outside _oid_rect does NOT emit the signal."""
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 120)

    commit = _make_commit()
    widget.set_commit(commit, [])

    oid_rect = QRect(60, 30, 320, 18)
    widget._oid_rect = oid_rect

    received: list[str] = []
    widget.commit_oid_copy_requested.connect(received.append)

    # Bottom-right corner is well outside the OID rect.
    _send_click(widget, widget.rect().bottomRight())

    assert received == []


def test_clear_resets_oid_rect(app, qtbot):
    """clear() must reset _oid_rect to None."""
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)

    # Seed _oid_rect as paintEvent would after a set_commit + paint pass.
    widget._oid_rect = QRect(0, 0, 100, 20)
    assert widget._oid_rect is not None

    widget.clear()
    assert widget._oid_rect is None


def test_clicking_ref_badge_emits_copy_signal_with_bare_name(app, qtbot):
    """Left-clicking a ref badge emits ref_copy_requested with its name.

    Badge rects are seeded directly (as paintEvent would after rendering)
    to avoid the PySide6/Windows paint-device crash described above.
    """
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 120)
    widget.set_commit(_make_commit(), ["main", "tag:v1.2.0", "origin/feature"])

    # 'tag:' and 'HEAD -> ' decorations are stripped from the copied text.
    widget._badge_rects = [
        (QRect(60, 30, 60, 18), "main"),
        (QRect(130, 30, 70, 18), "v1.2.0"),
        (QRect(210, 30, 110, 18), "origin/feature"),
    ]

    received: list[str] = []
    widget.ref_copy_requested.connect(received.append)

    _send_click(widget, QRect(130, 30, 70, 18).center())

    assert received == ["v1.2.0"]


def test_clicking_ref_badge_does_not_emit_oid_signal(app, qtbot):
    """A badge click must not also fire the OID copy signal."""
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 120)
    widget.set_commit(_make_commit(), ["main"])

    widget._oid_rect = QRect(60, 30, 320, 18)
    badge_rect = QRect(400, 30, 60, 18)
    widget._badge_rects = [(badge_rect, "main")]

    oid_received: list[str] = []
    ref_received: list[str] = []
    widget.commit_oid_copy_requested.connect(oid_received.append)
    widget.ref_copy_requested.connect(ref_received.append)

    _send_click(widget, badge_rect.center())

    assert ref_received == ["main"]
    assert oid_received == []


def test_clear_resets_badge_rects(app, qtbot):
    """clear() must drop the clickable badge rects."""
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)

    widget._badge_rects = [(QRect(0, 0, 50, 20), "main")]
    widget.clear()
    assert widget._badge_rects == []
