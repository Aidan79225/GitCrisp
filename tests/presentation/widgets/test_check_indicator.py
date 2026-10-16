"""The check indicator of a checkable row is painted by the delegate, every row.

Qt's macOS style on macOS 27 draws item-view check boxes outside the view for
every row but the first (QTBUG-150017), so these tests read the rendered
pixels of every row, including those past the first, rather than trusting
the style.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication, QListView, QStyleOptionViewItem

from git_gui.presentation.theme import ColorRole, get_theme_manager
from git_gui.presentation.widgets.check_indicator import (
    DASH,
    CheckIndicatorDelegate,
    check_gutter,
    check_indicator_rect,
    glyph_point,
    indicator_box,
)

_STATES = [Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked, Qt.CheckState.Unchecked]

# Antialiasing blends the box edge with its background by a few levels.
_ANTIALIAS_TOLERANCE = 12


def _color(role: ColorRole) -> QColor:
    return get_theme_manager().current.colors.as_qcolor(role)


def _same_colour(actual: QColor, expected: QColor) -> bool:
    return all(
        abs(a - e) <= _ANTIALIAS_TOLERANCE
        for a, e in zip(actual.getRgb()[:3], expected.getRgb()[:3], strict=True)
    )


def _pixel(image, point: QPoint) -> QColor:
    ratio = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * ratio), round(point.y() * ratio))


@pytest.fixture
def view(qtbot):
    model = QStandardItemModel()
    for state in _STATES:
        item = QStandardItem(f"row {state.name}")
        item.setCheckable(True)
        item.setCheckState(state)
        model.appendRow(item)
    v = QListView()
    v.setModel(model)
    v.setItemDelegate(CheckIndicatorDelegate(v))
    v.resize(400, 120)
    qtbot.addWidget(v)
    v.show()
    qtbot.waitExposed(v)
    QApplication.processEvents()
    return v


def _row_and_check(view, row: int):
    index = view.model().index(row, 0)
    opt = QStyleOptionViewItem()
    view.initViewItemOption(opt)
    opt.rect = view.visualRect(index)
    return QRect(opt.rect), check_indicator_rect(view.style(), opt, view)


def _box(view, row: int):
    row_rect, check = _row_and_check(view, row)
    return indicator_box(check_gutter(row_rect, check))


@pytest.mark.parametrize("row", range(len(_STATES)))
def test_box_sits_under_the_click_target(view, row):
    """The view hit-tests clicks against the style's check rect, so the box must
    be centred on it and stay inside the row, whatever the helpers do."""
    row_rect, check = _row_and_check(view, row)
    box = _box(view, row)
    assert abs(box.center().x() - check.center().x()) <= 1
    assert row_rect.top() <= box.top() and box.bottom() <= row_rect.bottom()


def _box_points(view, row: int) -> tuple[QPoint, QPoint]:
    """A point on the box's top border and one just inside it, clear of the glyph."""
    box = _box(view, row)
    x = box.center().x()
    return QPoint(x, box.top() + 1), QPoint(x, box.top() + 4)


def _dash_end(view, row: int) -> QPoint:
    """The pixel under the right end of the dash, which the tick never reaches."""
    end = glyph_point(_box(view, row), *DASH[-1])
    return QPoint(int(end.x()), int(end.y()))


@pytest.mark.parametrize(
    ("row", "border_role", "inside_role"),
    [
        (0, ColorRole.ON_PRIMARY_CONTAINER, ColorRole.ON_PRIMARY_CONTAINER),
        (1, ColorRole.ON_PRIMARY_CONTAINER, ColorRole.ON_PRIMARY_CONTAINER),
        (2, ColorRole.OUTLINE, ColorRole.SURFACE),
    ],
    ids=["checked", "partially-checked", "unchecked"],
)
def test_each_state_paints_its_own_box(view, row, border_role, inside_role):
    image = view.viewport().grab().toImage()
    border, inside = _box_points(view, row)
    assert _same_colour(_pixel(image, border), _color(border_role))
    assert _same_colour(_pixel(image, inside), _color(inside_role))


def test_partial_state_draws_a_dash_where_the_tick_does_not(view):
    """The dash end is bare fill under a tick and glyph colour under a dash, so a
    tick drawn for every filled state would fail here, whatever the box size."""
    image = view.viewport().grab().toImage()
    fill = _color(ColorRole.ON_PRIMARY_CONTAINER)
    assert _same_colour(_pixel(image, _dash_end(view, 0)), fill)
    assert not _same_colour(_pixel(image, _dash_end(view, 1)), fill)
