"""Tests for the per-row graph indent and the lane painter's geometry."""

from __future__ import annotations

from datetime import datetime

from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import LANE_ROLE, GraphModel, LaneData
from git_gui.presentation.widgets.graph_lane_painter import (
    GRAPH_GAP,
    LANE_W,
    MAX_GRAPH_LANES,
    NODE_R,
    NODE_STROKE_W,
    graph_width,
    row_graph_width,
    row_lane_span,
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


def test_graph_width_caps_so_commit_info_survives():
    assert graph_width(999) == graph_width(MAX_GRAPH_LANES)


def test_row_graph_width_without_lane_data_is_one_lane():
    assert row_graph_width(None) == graph_width(1)


def test_node_fits_within_its_lane():
    """The hollow node plus its stroke must not bleed into neighbouring lanes."""
    outer_diameter = (NODE_R + NODE_STROKE_W / 2) * 2
    assert outer_diameter < LANE_W


# ── row_lane_span ────────────────────────────────────────────────────────────


def test_row_lane_span_linear_history_is_one_everywhere(qtbot):
    model = GraphModel(
        [
            _make_commit("c", parents=["b"]),
            _make_commit("b", parents=["a"]),
            _make_commit("a"),
        ],
        {},
    )
    assert [row_lane_span(_lane_data(model, r)) for r in range(3)] == [1, 1, 1]


def test_row_lane_span_covers_the_merge_diagonal(qtbot):
    """The merge row draws out to the side lane, so its span includes it."""
    model = GraphModel([_make_commit("M", parents=["B", "D"]), _make_commit("B")], {})
    assert row_lane_span(_lane_data(model, 0)) == 2


def test_row_lane_span_narrows_once_the_side_lane_closes(qtbot):
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
    spans = [row_lane_span(_lane_data(model, r)) for r in range(5)]
    assert spans == [2, 2, 2, 2, 1]
    # The last row is therefore indented less than the rows above it.
    assert row_graph_width(_lane_data(model, 4)) < row_graph_width(_lane_data(model, 0))


def test_row_lane_span_never_clips_a_line_it_draws(qtbot):
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
        span = row_lane_span(ld)
        drawn = [ld.lane]
        for group in (ld.lines, ld.edges_in, ld.edges_out):
            for from_lane, to_lane, _ in group:
                drawn += [from_lane, to_lane]
        assert max(drawn) < span, f"row {row}: {drawn} exceeds span {span}"
