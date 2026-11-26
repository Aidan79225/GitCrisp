"""Tests for the per-row graph indent and the lane painter's geometry."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import LANE_ROLE, GraphModel, LaneData
from git_gui.presentation.theme import get_theme_manager
from git_gui.presentation.widgets.graph_lane_painter import (
    GRAPH_GAP,
    LANE_W,
    NODE_R,
    NODE_STROKE_W,
    graph_width,
    paint_lanes,
    row_graph_width,
)


def _make_commit(oid: str, parents: list[str] | None = None) -> Commit:
    return Commit(
        oid=oid,
        message="m",
        author="A <a@a.com>",
        timestamp=datetime(2026, 1, 1),
        parents=parents or [],
    )


def _lane_data(model: GraphModel, row: int) -> LaneData:
    return model.data(model.index(row, 0), LANE_ROLE)


# ── graph_width ──────────────────────────────────────────────────────────────


def test_graph_width_scales_with_lane_count():
    assert graph_width(1) == LANE_W + GRAPH_GAP
    assert graph_width(4) == 4 * LANE_W + GRAPH_GAP
    # Each extra lane costs exactly one lane width.
    assert graph_width(5) - graph_width(4) == LANE_W


def test_graph_width_floors_at_one_lane():
    """Zero or negative lane counts must not collapse the graph."""
    assert graph_width(0) == graph_width(1)
    assert graph_width(-3) == graph_width(1)


def test_graph_width_has_no_cap_so_no_lane_is_left_undrawn():
    """A history of any width gets room for every lane; the list scrolls it."""
    assert graph_width(999) == 999 * LANE_W + GRAPH_GAP


def test_row_graph_width_without_lane_data_is_zero():
    """No lane data means no graph on the row, so the commit info hugs the edge.

    This is what a path-filtered listing renders: the commits are a sparse
    subset of history, so the model withholds lane data entirely.
    """
    assert row_graph_width(None) == 0


def test_node_fits_within_its_lane():
    """The hollow node plus its stroke must not bleed into neighbouring lanes."""
    outer_diameter = (NODE_R + NODE_STROKE_W / 2) * 2
    assert outer_diameter < LANE_W


# ── LaneData.span ────────────────────────────────────────────────────────────


def test_lane_span_linear_history_is_one_everywhere(qtbot):
    model = GraphModel(
        [
            _make_commit("c", parents=["b"]),
            _make_commit("b", parents=["a"]),
            _make_commit("a"),
        ],
        {},
    )
    assert [_lane_data(model, r).span for r in range(3)] == [1, 1, 1]


def test_lane_span_covers_the_merge_diagonal(qtbot):
    """The merge row draws out to the side lane, so its span includes it."""
    model = GraphModel([_make_commit("M", parents=["B", "D"]), _make_commit("B")], {})
    assert _lane_data(model, 0).span == 2


def test_lane_span_narrows_once_the_side_lane_closes(qtbot):
    """A row past the end of a side lane must not be indented by it.

    This is the whole point of a per-row indent: rows below the branch point
    hug the left edge even though rows above them are two lanes wide. The
    branch point itself still spans two lanes — it draws the diagonal the side
    lane converges along.
    """
    #  M   merge of B and D
    #  |\
    #  B |  branch tip
    #  |/
    #  A   branch point — draws the converging diagonal
    #  |
    #  Z   only lane 0 left
    model = GraphModel(
        [
            _make_commit("M", parents=["B", "D"]),
            _make_commit("B", parents=["A"]),
            _make_commit("D", parents=["A"]),
            _make_commit("A", parents=["Z"]),
            _make_commit("Z"),
        ],
        {},
    )
    spans = [_lane_data(model, r).span for r in range(5)]
    assert spans == [2, 2, 2, 2, 1]
    # The last row is therefore indented less than the rows above it.
    assert row_graph_width(_lane_data(model, 4)) < row_graph_width(_lane_data(model, 0))


def test_lane_span_never_clips_a_line_it_draws(qtbot):
    """Every lane a row paints into must fall inside that row's own span.

    Guards the indent against hiding graph geometry behind the commit info.
    """
    model = GraphModel(
        [
            _make_commit("M", parents=["B", "D"]),
            _make_commit("B", parents=["A"]),
            _make_commit("D", parents=["A"]),
            _make_commit("A", parents=["Z"]),
            _make_commit("Z"),
        ],
        {},
    )
    for row in range(5):
        ld = _lane_data(model, row)
        span = ld.span
        drawn = [ld.lane]
        for group in (ld.lines, ld.edges_in, ld.edges_out):
            for from_lane, to_lane, _ in group:
                drawn += [from_lane, to_lane]
        assert max(drawn) < span, f"row {row}: {drawn} exceeds span {span}"


# ── Lane colours ─────────────────────────────────────────────────────────────


def test_a_colour_index_past_the_theme_palette_wraps_to_its_first_colour(qtbot):
    palette = get_theme_manager().current.colors.graph_lane_colors
    past_the_end = len(palette)
    lane = LaneData(lane=0, color_idx=past_the_end, n_lanes=1, lines=[(0, 0, past_the_end)])
    image = QImage(LANE_W, 4 * LANE_W, QImage.Format_ARGB32)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    paint_lanes(painter, image.rect(), lane, selected=False)
    painter.end()

    assert image.pixelColor(LANE_W // 2, 1).name() == QColor(palette[0]).name()


# ── Scrolled lanes ───────────────────────────────────────────────────────────


def _node_outline_painted(image: QImage, lane_x: int) -> bool:
    """Whether the hollow node's outline is drawn at the lane centred on `lane_x`."""
    return image.pixelColor(lane_x + NODE_R, image.height() // 2 - 1).alpha() > 0


def _paint_node_row(*, lane: int, x_offset: int, width: int = 12 * LANE_W) -> QImage:
    image = QImage(width, 4 * LANE_W, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    paint_lanes(
        painter,
        image.rect(),
        LaneData(lane=lane, color_idx=0, n_lanes=lane + 1),
        selected=False,
        x_offset=x_offset,
    )
    painter.end()
    return image


def test_an_unscrolled_graph_paints_a_lane_at_its_own_column(qtbot):
    image = _paint_node_row(lane=3, x_offset=0)

    assert _node_outline_painted(image, 3 * LANE_W + LANE_W // 2)


def test_scrolling_the_graph_moves_every_lane_left_by_the_offset(qtbot):
    image = _paint_node_row(lane=3, x_offset=2 * LANE_W)

    assert _node_outline_painted(image, 1 * LANE_W + LANE_W // 2)
    assert not _node_outline_painted(image, 3 * LANE_W + LANE_W // 2)


def test_a_lane_scrolled_past_the_left_edge_is_not_painted_at_all(qtbot):
    image = _paint_node_row(lane=1, x_offset=5 * LANE_W)

    assert all(
        image.pixelColor(x, y).alpha() == 0
        for x in range(image.width())
        for y in range(image.height())
    )
