# git_gui/presentation/widgets/graph_lane_delegate.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from git_gui.presentation.theme import get_theme_manager

LANE_W = 16   # pixels per lane column
NODE_R = 4    # commit node circle radius


def _lane_colors() -> list[str]:
    return get_theme_manager().current.colors.graph_lane_colors


def _selection_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("primary")


def _divider_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("outline")


def _lx(rect_left: int, lane: int) -> int:
    """X coordinate for the center of a lane."""
    return rect_left + lane * LANE_W + LANE_W // 2


class GraphLaneDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        lane_data = index.data(Qt.UserRole + 1)
        if lane_data is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect

        # ── Selection highlight ───────────────────────────────────────────────
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, _selection_color())

        lane_colors = _lane_colors()
        n_colors = len(lane_colors)

        left = rect.left()
        top = rect.top()
        bot = rect.bottom()
        mid = (top + bot) // 2

        # 1. Pass-through lines (full row height, diagonal if lane changes)
        for top_lane, bot_lane, ci in lane_data.lines:
            painter.setPen(QPen(QColor(lane_colors[ci % n_colors]), 2))
            painter.drawLine(_lx(left, top_lane), top, _lx(left, bot_lane), bot)

        # 2. Incoming line (top of cell → commit node, only if lane was active above)
        if lane_data.has_incoming:
            painter.setPen(QPen(QColor(lane_colors[lane_data.color_idx % n_colors]), 2))
            lx = _lx(left, lane_data.lane)
            painter.drawLine(lx, top, lx, mid)

        # 2b. Incoming edges from converging lanes (top of cell → commit node, diagonal)
        for from_lane, to_lane, ci in lane_data.edges_in:
            painter.setPen(QPen(QColor(lane_colors[ci % n_colors]), 2))
            painter.drawLine(_lx(left, from_lane), top, _lx(left, to_lane), mid)

        # 3. Outgoing edges (commit node → bottom of cell, straight or diagonal)
        for from_lane, to_lane, ci in lane_data.edges_out:
            painter.setPen(QPen(QColor(lane_colors[ci % n_colors]), 2))
            painter.drawLine(_lx(left, from_lane), mid, _lx(left, to_lane), bot)

        # 4. Commit node (filled circle drawn last so it sits on top of lines)
        lx = _lx(left, lane_data.lane)
        node_color = QColor(lane_colors[lane_data.color_idx % n_colors])
        painter.setBrush(node_color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(lx - NODE_R, mid - NODE_R, NODE_R * 2, NODE_R * 2)

        # ── Bottom divider ────────────────────────────────────────────────────
        painter.setPen(_divider_color())
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        painter.restore()
