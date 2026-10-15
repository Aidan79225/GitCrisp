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
)

from git_gui.presentation.theme import ColorRole, get_theme_manager

# The same geometry as the QCheckBox rule in qss_template.py: a 14px box
# inside a 2px border.
BOX_SIZE = 18
BORDER = 2
RADIUS = 3
# Glyphs in the 14px inner box, as drawn by arts/ic_check.svg.
_TICK = ((3.0, 7.0), (6.0, 10.0), (11.0, 4.0))
_DASH = ((3.0, 7.0), (11.0, 7.0))


def indicator_box(gutter: QRect) -> QRect:
    """The square the indicator is drawn in, centred in the row's check gutter.

    The box is the QCheckBox size where the gutter allows it. Styles differ in
    how wide a column they reserve for the indicator (Fusion and Windows give
    less than macOS), and a box wider than that column would run into the
    text, so it shrinks to fit, two pixels of overhang allowed.
    """
    side = min(BOX_SIZE, gutter.width() + 2, gutter.height())
    box = QRect(0, 0, side, side)
    box.moveCenter(gutter.center())
    return box


def paint_check_indicator(
    painter: QPainter, gutter: QRect, state: Qt.CheckState, background: QColor
) -> None:
    """Draw the indicator for ``state`` in the row's check ``gutter``.

    ``gutter`` is first filled with ``background`` so that whatever the
    platform style drew there, whole or in part, cannot show around the box.
    """
    colors = get_theme_manager().current.colors
    checked = state != Qt.CheckState.Unchecked
    accent = colors.as_qcolor(ColorRole.ON_PRIMARY_CONTAINER)
    surface = colors.as_qcolor(ColorRole.SURFACE)

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.fillRect(gutter, background)

    box = indicator_box(gutter)
    painter.setPen(QPen(accent if checked else colors.as_qcolor(ColorRole.OUTLINE), BORDER))
    painter.setBrush(accent if checked else surface)
    # The pen straddles the path, so inset by half of it to keep the stroke
    # inside the box.
    half = BORDER / 2
    painter.drawRoundedRect(QRectF(box).adjusted(half, half, -half, -half), RADIUS, RADIUS)

    if checked:
        glyph = _TICK if state == Qt.CheckState.Checked else _DASH
        pen = QPen(colors.as_qcolor(ColorRole.PRIMARY_CONTAINER), BORDER)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        origin = QPointF(box.left() + BORDER, box.top() + BORDER)
        scale = (box.width() - 2 * BORDER) / (BOX_SIZE - 2 * BORDER)
        painter.drawPolyline([origin + QPointF(x * scale, y * scale) for x, y in glyph])

    painter.restore()


class CheckIndicatorDelegate(QStyledItemDelegate):
    """A QStyledItemDelegate that paints the check indicator of checkable rows.

    The platform style still lays the row out as if it drew the box, so the
    indicator sits where the view expects clicks (see
    ``FileListView._checkbox_rect``); it is only the drawing that is replaced.
    """

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)
        # Qt draws an indicator for any row with a check state, whether or not
        # the user may toggle it, so follow the same rule.
        state = index.data(Qt.CheckStateRole)
        if state is None:
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        check = style.subElementRect(QStyle.SE_ItemViewItemCheckIndicator, opt, widget)
        # The style's rect is only as tall as its own indicator and may sit at
        # the top of a taller row; the box is centred on the row instead.
        gutter = QRect(check.left(), option.rect.top(), check.width(), option.rect.height())

        if option.state & QStyle.State_Selected:
            background = get_theme_manager().current.colors.as_qcolor(ColorRole.PRIMARY)
        else:
            background = opt.palette.color(QPalette.Base)
        paint_check_indicator(painter, gutter, Qt.CheckState(state), background)
