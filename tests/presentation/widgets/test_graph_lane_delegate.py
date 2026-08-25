"""Tests for the graph column's sizing helper and node rendering constants."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from PySide6.QtWidgets import QWidget

from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import GraphModel
from git_gui.presentation.widgets.graph import GraphWidget
from git_gui.presentation.widgets.graph_lane_delegate import (
    GRAPH_COL_PAD,
    LANE_W,
    MAX_GRAPH_LANES,
    NODE_R,
    NODE_STROKE_W,
    graph_column_width,
)


def _make_commit(oid: str, parents: list[str] | None = None) -> Commit:
    return Commit(
        oid=oid,
        message="m",
        author="A <a@a.com>",
        timestamp=datetime(2026, 1, 1),
        parents=parents or [],
    )


def test_graph_column_width_scales_with_lane_count():
    assert graph_column_width(1) == LANE_W + GRAPH_COL_PAD
    assert graph_column_width(4) == 4 * LANE_W + GRAPH_COL_PAD
    # Each extra lane costs exactly one lane width.
    assert graph_column_width(5) - graph_column_width(4) == LANE_W


def test_graph_column_width_floors_at_one_lane():
    """Zero or negative lane counts must not collapse the column."""
    assert graph_column_width(0) == graph_column_width(1)
    assert graph_column_width(-3) == graph_column_width(1)


def test_graph_column_width_caps_so_info_column_survives():
    assert graph_column_width(999) == graph_column_width(MAX_GRAPH_LANES)


def test_node_fits_within_its_lane():
    """The hollow node plus its stroke must not bleed into neighbouring lanes."""
    outer_diameter = (NODE_R + NODE_STROKE_W / 2) * 2
    assert outer_diameter < LANE_W


def test_widget_syncs_column_width_to_widest_row(qtbot):
    """_sync_graph_column_width tracks the model's current lane count."""
    w = GraphWidget.__new__(GraphWidget)
    QWidget.__init__(w)
    w._view = MagicMock()
    w._model = GraphModel([], {})
    qtbot.addWidget(w)

    w._sync_graph_column_width()
    w._view.setColumnWidth.assert_called_with(0, graph_column_width(1))

    # A merge opens a second lane — the column grows to match.
    w._model.reload(
        [
            _make_commit("M", parents=["B", "D"]),
            _make_commit("B", parents=["A"]),
            _make_commit("A"),
        ],
        {},
    )
    w._sync_graph_column_width()
    w._view.setColumnWidth.assert_called_with(0, graph_column_width(2))
