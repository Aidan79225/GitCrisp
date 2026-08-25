# git_gui/presentation/widgets/graph_lane_delegate.py
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from git_gui.presentation.theme import get_theme_manager

LANE_W = 16  # pixels per lane column
NODE_R = 5  # commit node circle radius (outline centre)
NODE_STROKE_W = 2  # commit node outline thickness
GRAPH_COL_PAD = 4  # breathing room to the right of the last lane
MAX_GRAPH_LANES = 16  # cap so a very wide graph can't crowd out the info column


def _lane_colors() -> list[str]:
    return get_theme_manager().current.colors.graph_lane_colors


def _selection_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("primary")


def _divider_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("outline")


def _node_fill_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("surface")


def _lx(rect_left: int, lane: int) -> int:
    """X coordinate for the center of a lane."""
    return rect_left + lane * LANE_W + LANE_W // 2


def graph_column_width(n_lanes: int) -> int:
    """Pixel width the graph column needs to draw ``n_lanes`` parallel lanes."""
    lanes = min(max(n_lanes, 1), MAX_GRAPH_LANES)
    return lanes * LANE_W + GRAPH_COL_PAD


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

        # 4. Commit node — hollow circle drawn last so it sits on top of the
        #    lines. The fill matches the row background so lines passing under
        #    the node are masked out rather than showing through the middle.
        lx = _lx(left, lane_data.lane)
        node_color = QColor(lane_colors[lane_data.color_idx % n_colors])
        if option.state & QStyle.State_Selected:
            painter.setBrush(_selection_color())
        else:
            painter.setBrush(_node_fill_color())
        painter.setPen(QPen(node_color, NODE_STROKE_W))
        painter.drawEllipse(QPointF(lx, mid), NODE_R, NODE_R)

        # ── Bottom divider ────────────────────────────────────────────────────
        painter.setPen(_divider_color())
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        painter.restore()
