"""A check indicator the delegate paints itself, in theme colors.

An item view normally asks the platform style to draw the check box of a
checkable row. On macOS 27 the macOS style of Qt 6.11 draws it outside the
view for every row but the first (QTBUG-150017, fixed in Qt 6.12.1), so the
working-tree list lost its checkboxes. Painting the box here makes it
independent of the platform style and gives it the MD3 look that the QSS in
qss_template.py already gives a standalone QCheckBox.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from git_gui.presentation.theme import (
    CHECKBOX_BORDER,
    CHECKBOX_INNER_SIZE,
    CHECKBOX_RADIUS,
    ColorRole,
    Colors,
    get_theme_manager,
)

BORDER = CHECKBOX_BORDER
RADIUS = CHECKBOX_RADIUS
_INNER_SIZE = CHECKBOX_INNER_SIZE
BOX_SIZE = _INNER_SIZE + 2 * BORDER
# How far the box may stick out of a check column narrower than itself.
_GUTTER_OVERHANG = 2
# Glyphs in the _INNER_SIZE box; the tick traces arts/ic_check.svg.
_TICK = ((3.0, 7.0), (6.0, 10.0), (11.0, 4.0))
_DASH = ((3.0, 7.0), (11.0, 7.0))
DASH_END = _DASH[-1]


def check_indicator_rect(
    style: QStyle, option: QStyleOptionViewItem, widget: QWidget | None
) -> QRect:
    """Where the style would draw the row's check box.

    The view hit-tests clicks against this rect and the delegate paints into
    it, so both ask here rather than each working it out.
    """
    option.features |= QStyleOptionViewItem.HasCheckIndicator
    return style.subElementRect(QStyle.SE_ItemViewItemCheckIndicator, option, widget)


def check_gutter(row: QRect, check: QRect) -> QRect:
    """The column the indicator owns: the style's check rect at full row height.

    The style's rect is only as tall as its own indicator and may sit at the
    top of a taller row, so the box is centred on the row instead.
    """
    return QRect(check.left(), row.top(), check.width(), row.height())


def indicator_box(gutter: QRect) -> QRect:
    """The square the indicator is drawn in, centred in the row's check gutter.

    The box is the QCheckBox size where the gutter allows it. Styles differ in
    how wide a column they reserve for the indicator (Fusion and Windows give
    less than macOS), and a box wider than that column would run into the
    text, so it shrinks to fit.
    """
    side = min(BOX_SIZE, gutter.width() + _GUTTER_OVERHANG, gutter.height())
    box = QRect(0, 0, side, side)
    box.moveCenter(gutter.center())
    return box


def glyph_point(box: QRect, x: float, y: float) -> QPointF:
    """Where a point of the ``_INNER_SIZE`` glyph lands inside ``box``."""
    scale = (box.width() - 2 * BORDER) / _INNER_SIZE
    return QPointF(box.left() + BORDER + x * scale, box.top() + BORDER + y * scale)


def paint_check_indicator(
    painter: QPainter, gutter: QRect, state: Qt.CheckState, background: QColor
) -> None:
    """Draw the indicator for ``state`` in the row's check ``gutter``.

    ``gutter`` is first filled with ``background`` so that whatever the
    platform style drew there, whole or in part, cannot show around the box.
    """
    colors = get_theme_manager().current.colors
    box = indicator_box(gutter)
    filled = state != Qt.CheckState.Unchecked

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.fillRect(gutter, background)
    _draw_box(painter, box, filled, colors)
    if filled:
        _draw_glyph(painter, box, state, colors)
    painter.restore()


def _draw_box(painter: QPainter, box: QRect, filled: bool, colors: Colors) -> None:
    accent = colors.as_qcolor(ColorRole.ON_PRIMARY_CONTAINER)
    painter.setPen(QPen(accent if filled else colors.as_qcolor(ColorRole.OUTLINE), BORDER))
    painter.setBrush(accent if filled else colors.as_qcolor(ColorRole.SURFACE))
    # The pen straddles the path, so inset by half of it to keep the stroke
    # inside the box.
    half = BORDER / 2
    painter.drawRoundedRect(QRectF(box).adjusted(half, half, -half, -half), RADIUS, RADIUS)


def _draw_glyph(painter: QPainter, box: QRect, state: Qt.CheckState, colors: Colors) -> None:
    glyph = _TICK if state == Qt.CheckState.Checked else _DASH
    pen = QPen(colors.as_qcolor(ColorRole.PRIMARY_CONTAINER), BORDER)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPolyline([glyph_point(box, x, y) for x, y in glyph])


class CheckIndicatorDelegate(QStyledItemDelegate):
    """A QStyledItemDelegate that paints the check indicator of checkable rows.

    The platform style still lays the row out as if it drew the box; only the
    drawing is replaced. A selected row is filled with the theme's primary
    before the base paint, as the app's other delegates do, so the gutter and
    the row behind it come from one colour.
    """

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, self._row_background(option))
        super().paint(painter, option, index)
        # Qt draws an indicator for any row with a check state, whether or not
        # the user may toggle it, so follow the same rule.
        state = index.data(Qt.CheckStateRole)
        if state is None:
            return
        gutter = self._gutter_for(option, index)
        paint_check_indicator(painter, gutter, Qt.CheckState(state), self._row_background(option))

    def _row_background(self, option: QStyleOptionViewItem) -> QColor:
        if option.state & QStyle.State_Selected:
            return get_theme_manager().current.colors.as_qcolor(ColorRole.PRIMARY)
        return option.palette.color(QPalette.Base)

    def _gutter_for(self, option: QStyleOptionViewItem, index) -> QRect:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        return check_gutter(option.rect, check_indicator_rect(style, opt, widget))
