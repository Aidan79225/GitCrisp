# git_gui/presentation/widgets/graph_lane_painter.py
"""Painting primitives for the lane graph drawn at the left of each commit row.

This module owns the geometry of the graph only. The row delegate
(``commit_row_delegate``) decides where the graph ends and the commit info
begins, and calls :func:`paint_lanes` with that sub-rect.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QColor, QPainter, QPen

from git_gui.presentation.models.graph_model import LaneData
from git_gui.presentation.theme import get_theme_manager

LANE_W = 16  # pixels per lane column
NODE_R = 5  # commit node circle radius (outline centre)
NODE_STROKE_W = 2  # commit node outline thickness
GRAPH_GAP = 4  # breathing room between the last lane and the commit info
MAX_GRAPH_LANES = 16  # cap so a very wide graph can't crowd out the commit info


def _lane_colors() -> list[str]:
    return get_theme_manager().current.colors.graph_lane_colors


def _selection_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("primary")


def _node_fill_color() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("surface")


def _lx(rect_left: int, lane: int) -> int:
    """X coordinate for the center of a lane."""
    return rect_left + lane * LANE_W + LANE_W // 2


def row_lane_span(lane_data: LaneData) -> int:
    """How many lane columns this single row actually paints into.

    Unlike ``LaneData.n_lanes`` (the lane count of the whole history at this
    point), this looks only at what is drawn on this row: the commit node plus
    both endpoints of every line and edge. Rows below a merge that has already
    closed therefore report a narrower span, letting their commit info sit
    further left.
    """
    lanes = [lane_data.lane]
    for endpoints in (lane_data.lines, lane_data.edges_in, lane_data.edges_out):
        for from_lane, to_lane, _ in endpoints:
            lanes.append(from_lane)
            lanes.append(to_lane)
    return max(lanes) + 1


def graph_width(n_lanes: int) -> int:
    """Pixel width needed to paint ``n_lanes`` parallel lanes, plus the gap."""
    lanes = min(max(n_lanes, 1), MAX_GRAPH_LANES)
    return lanes * LANE_W + GRAPH_GAP


def row_graph_width(lane_data: LaneData | None) -> int:
    """Width the graph needs on this row — the per-row indent for commit info.

    No lane data means no graph on this row (a path-filtered listing, where the
    commits are a sparse subset and lanes would be meaningless), so the commit
    info starts at the very left edge.
    """
    if lane_data is None:
        return 0
    return graph_width(row_lane_span(lane_data))


def paint_lanes(painter: QPainter, rect: QRect, lane_data: LaneData, *, selected: bool) -> None:
    """Draw one row of the lane graph inside ``rect``.

    ``rect`` is the graph's slice of the row; painting is clipped to it so a
    history wider than ``MAX_GRAPH_LANES`` can never bleed into the commit info.
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setClipRect(rect)

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

    # 4. Commit node — hollow circle drawn last so it sits on top of the lines.
    #    The fill matches the row background so lines passing under the node are
    #    masked out rather than showing through the middle.
    lx = _lx(left, lane_data.lane)
    node_color = QColor(lane_colors[lane_data.color_idx % n_colors])
    painter.setBrush(_selection_color() if selected else _node_fill_color())
    painter.setPen(QPen(node_color, NODE_STROKE_W))
    painter.drawEllipse(QPointF(lx, mid), NODE_R, NODE_R)

    painter.restore()
