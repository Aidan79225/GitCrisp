# git_gui/presentation/widgets/graph_lane_delegate.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

LANE_W = 16   # pixels per lane column
NODE_R = 4    # commit node circle radius

LANE_COLORS = [
    "#4fc1ff",  # blue
    "#f9c74f",  # yellow
    "#90be6d",  # green
    "#f8961e",  # orange
    "#c77dff",  # purple
    "#f94144",  # red
    "#43aa8b",  # teal
    "#adb5bd",  # grey
]


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
            painter.fillRect(rect, QColor("#264f78"))

        left = rect.left()
        top = rect.top()
        bot = rect.bottom()
        mid = (top + bot) // 2

        # 1. Pass-through lines (full row height, diagonal if lane changes)
        for top_lane, bot_lane, ci in lane_data.lines:
            painter.setPen(QPen(QColor(LANE_COLORS[ci % len(LANE_COLORS)]), 2))
            painter.drawLine(_lx(left, top_lane), top, _lx(left, bot_lane), bot)

        # 2. Incoming line (top of cell → commit node, only if lane was active above)
        if lane_data.has_incoming:
            painter.setPen(QPen(QColor(LANE_COLORS[lane_data.color_idx % len(LANE_COLORS)]), 2))
            lx = _lx(left, lane_data.lane)
            painter.drawLine(lx, top, lx, mid)

        # 3. Outgoing edges (commit node → bottom of cell, straight or diagonal)
        for from_lane, to_lane, ci in lane_data.edges_out:
            painter.setPen(QPen(QColor(LANE_COLORS[ci % len(LANE_COLORS)]), 2))
            painter.drawLine(_lx(left, from_lane), mid, _lx(left, to_lane), bot)

        # 4. Commit node (filled circle drawn last so it sits on top of lines)
        lx = _lx(left, lane_data.lane)
        node_color = QColor(LANE_COLORS[lane_data.color_idx % len(LANE_COLORS)])
        painter.setBrush(node_color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(lx - NODE_R, mid - NODE_R, NODE_R * 2, NODE_R * 2)

        # ── Bottom divider ────────────────────────────────────────────────────
        painter.setPen(QColor("#30363d"))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        painter.restore()
