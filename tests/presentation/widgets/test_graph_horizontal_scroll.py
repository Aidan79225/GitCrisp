"""A history with more lanes than fit beside the commit info scrolls sideways.

The graph column takes at most a share of the list's width, so the commit info
always keeps room however many branches run in parallel; the lanes beyond are
reached with a scrollbar under the graph, the wheel, or by selecting a commit.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from git_gui.domain.entities import Commit
from git_gui.presentation.widgets.graph_lane_painter import (
    GRAPH_COLUMN_SHARE,
    LANE_W,
    MIN_GRAPH_COLUMN_LANES,
    graph_column_width,
    graph_width,
)
from tests.presentation.widgets.graph_helpers import graph_widget

LANES = 40


def _commit(oid: str, parents: list[str] | None = None) -> Commit:
    return Commit(
        oid=oid,
        message=oid,
        author="A <a@example.com>",
        timestamp=datetime(2026, 1, 1),
        parents=parents or [],
    )


def _wide_history(lanes: int) -> list[Commit]:
    """`lanes` tips that all descend from one root: the root row spans every lane."""
    tips = [_commit(f"tip{i}", ["root"]) for i in range(lanes)]
    return [*tips, _commit("root")]


def _shown(qtbot, commits: list[Commit], width: int = 900):
    widget = graph_widget(qtbot)
    widget.resize(width, 500)
    widget.show()
    qtbot.waitExposed(widget)
    widget._model.reload(commits, {})
    return widget


def _bar(widget):
    return widget._graph_scrollbar


def _wheel(widget, *, dx: int = 0, dy: int = 0, modifiers=Qt.NoModifier) -> None:
    view = widget._view
    event = QWheelEvent(
        QPointF(40, 40),
        view.viewport().mapToGlobal(QPointF(40, 40)),
        QPoint(0, 0),
        QPoint(dx, dy),
        Qt.NoButton,
        modifiers,
        Qt.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(view.viewport(), event)


def test_a_history_that_fits_beside_the_info_has_no_scrollbar(qtbot):
    widget = _shown(qtbot, _wide_history(3))

    assert not _bar(widget).isVisible()


def test_a_history_wider_than_the_graph_column_gets_a_scrollbar(qtbot):
    widget = _shown(qtbot, _wide_history(LANES))

    assert _bar(widget).isVisible()


def test_the_scrollbar_reaches_exactly_the_end_of_the_widest_row(qtbot):
    widget = _shown(qtbot, _wide_history(LANES))
    bar = _bar(widget)

    # Scrolled all the way, the column ends where the widest row's lanes end.
    assert bar.maximum() + bar.pageStep() == graph_width(LANES)


def test_the_graph_column_takes_a_share_of_the_list_and_never_all_of_it(qtbot):
    widget = _shown(qtbot, _wide_history(LANES))
    viewport_w = widget._view.viewport().width()

    column = _bar(widget).pageStep()

    assert column == max(int(viewport_w * GRAPH_COLUMN_SHARE), graph_width(MIN_GRAPH_COLUMN_LANES))
    assert column < viewport_w


def test_the_scrollbar_sits_under_the_graph_column_only(qtbot):
    widget = _shown(qtbot, _wide_history(LANES))
    bar = _bar(widget)

    assert bar.width() == bar.pageStep()


def test_a_wider_list_gives_the_graph_more_room_and_less_to_scroll(qtbot):
    widget = _shown(qtbot, _wide_history(LANES), width=700)
    narrow_max = _bar(widget).maximum()

    widget.resize(1500, 500)
    qtbot.waitUntil(lambda: _bar(widget).maximum() < narrow_max)


def test_scrolling_the_bar_scrolls_the_painted_graph(qtbot):
    widget = _shown(qtbot, _wide_history(LANES))

    _bar(widget).setValue(5 * LANE_W)

    assert widget._view.itemDelegate().graph_scroll == 5 * LANE_W


def test_the_wheel_with_shift_held_scrolls_the_graph_sideways(qtbot):
    widget = _shown(qtbot, _wide_history(LANES))
    top = widget._view.verticalScrollBar().value()

    _wheel(widget, dy=-120, modifiers=Qt.ShiftModifier)

    assert _bar(widget).value() > 0
    assert widget._view.verticalScrollBar().value() == top


def test_a_sideways_wheel_scrolls_the_graph(qtbot):
    widget = _shown(qtbot, _wide_history(LANES))

    _wheel(widget, dx=-120)

    assert _bar(widget).value() > 0


def test_the_plain_wheel_still_scrolls_the_list_not_the_graph(qtbot):
    widget = _shown(qtbot, _wide_history(200))
    widget._view.verticalScrollBar().setValue(0)

    _wheel(widget, dy=-120)

    assert _bar(widget).value() == 0
    assert widget._view.verticalScrollBar().value() > 0


def test_selecting_a_commit_on_a_far_lane_scrolls_its_node_into_view(qtbot):
    widget = _shown(qtbot, _wide_history(LANES))
    far_row = LANES - 1  # the tip on the last lane

    widget._view.selectRow(far_row)

    bar = _bar(widget)
    node_x = (LANES - 1) * LANE_W + LANE_W // 2
    assert bar.value() <= node_x <= bar.value() + bar.pageStep()


def test_selecting_a_commit_already_in_view_leaves_the_scroll_alone(qtbot):
    widget = _shown(qtbot, _wide_history(LANES))
    _bar(widget).setValue(2 * LANE_W)

    widget._view.selectRow(3)  # lane 3 is inside the column at that scroll

    assert _bar(widget).value() == 2 * LANE_W


def test_a_narrower_history_hides_the_scrollbar_and_rewinds_the_graph(qtbot):
    widget = _shown(qtbot, _wide_history(LANES))
    _bar(widget).setValue(10 * LANE_W)

    widget._model.reload(_wide_history(3), {})

    assert not _bar(widget).isVisible()
    assert widget._view.itemDelegate().graph_scroll == 0


def test_a_later_page_that_widens_the_graph_extends_the_scrollbar(qtbot):
    # The first page ends before the root, so every tip's lane is still open when the next arrives.
    first_page = _wide_history(LANES)[:-1]
    widget = _shown(qtbot, first_page)
    before = _bar(widget).maximum()

    widget._model.append([_commit(f"extra{i}", ["root"]) for i in range(10)], {})

    assert _bar(widget).maximum() == before + 10 * LANE_W


def test_a_listing_without_a_graph_has_no_scrollbar(qtbot):
    widget = _shown(qtbot, [])
    widget._model.reload(_wide_history(LANES), {}, show_graph=False)

    assert not _bar(widget).isVisible()


def test_a_touchpad_swipe_that_is_mostly_vertical_still_scrolls_the_list(qtbot):
    """A diagonal swipe carries a little x with a lot of y; the y must not be lost."""
    widget = _shown(qtbot, _wide_history(200))
    widget._view.verticalScrollBar().setValue(0)

    _wheel(widget, dx=3, dy=-120)

    assert widget._view.verticalScrollBar().value() > 0
    assert _bar(widget).value() == 0


def test_a_sideways_wheel_over_a_graph_that_fits_does_not_swallow_the_event(qtbot):
    widget = _shown(qtbot, _wide_history(3))
    seen = []
    widget._view.graph_scroll_requested.connect(seen.append)

    _wheel(widget, dx=-120)

    assert seen == []


def test_small_wheel_steps_add_up_to_whole_notches(qtbot):
    """A touchpad reports many tiny deltas; none of them may be rounded away."""
    widget = _shown(qtbot, _wide_history(LANES))

    for _ in range(10):
        _wheel(widget, dx=-12)

    assert _bar(widget).value() == 3 * LANE_W


def test_a_selected_far_lane_is_revealed_even_before_the_widget_is_shown(qtbot):
    widget = graph_widget(qtbot)
    widget.resize(900, 500)
    widget._model.reload(_wide_history(LANES), {})

    widget._view.selectRow(LANES - 1)

    bar = _bar(widget)
    node_x = (LANES - 1) * LANE_W + LANE_W // 2
    assert bar.value() <= node_x <= bar.value() + bar.pageStep()


def test_the_column_follows_the_viewport_when_the_vertical_scrollbar_appears(qtbot):
    widget = _shown(qtbot, _wide_history(LANES)[:3])
    assert not widget._view.verticalScrollBar().isVisible()

    widget._model.reload(_wide_history(200), {})
    qtbot.waitUntil(lambda: widget._view.verticalScrollBar().isVisible())

    assert _bar(widget).pageStep() == graph_column_width(widget._view.viewport().width())
