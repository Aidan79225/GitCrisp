"""Tests for the commit list's file-history (path filter) mode."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from PySide6.QtWidgets import QWidget

from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import LANE_ROLE, GraphModel
from git_gui.presentation.widgets.graph import GraphWidget
from git_gui.presentation.widgets.graph_lane_painter import row_graph_width


def _make_commit(oid: str, parents: list[str] | None = None) -> Commit:
    return Commit(
        oid=oid,
        message="m",
        author="A <a@a.com>",
        timestamp=datetime(2026, 1, 1),
        parents=parents or [],
    )


def _make_widget(qtbot) -> GraphWidget:
    """Minimal GraphWidget with __init__ bypassed, as the sibling graph tests do."""
    w = GraphWidget.__new__(GraphWidget)
    QWidget.__init__(w)
    w._queries = MagicMock()
    w._model = GraphModel([], {})
    w._loading = False
    w._loaded_count = 0
    w._has_more = True
    w._reload_limit = 50
    w._pending_scroll_oid = None
    w._pending_merge_base = None
    w._pending_search = None
    w._extra_tips = None
    w._selected_oid = None
    w._scroll_anchor_oid = None
    w._first_parent = False
    w._path_filter = None
    w._path_filter_bar = MagicMock()
    w._path_filter_bar.follow.return_value = True
    w._view = MagicMock()
    w._stash_btn = MagicMock()
    w._search_bar = MagicMock()
    w._search_matches = []
    w._search_idx = -1
    qtbot.addWidget(w)
    return w


# ── Entering and leaving the mode ────────────────────────────────────────────


def test_set_path_filter_announces_the_path_and_reloads(qtbot):
    w = _make_widget(qtbot)
    announced: list[object] = []
    w.path_filter_changed.connect(announced.append)
    w.reload = MagicMock()

    w.set_path_filter("src/diff.py")

    assert w._path_filter == "src/diff.py"
    w._path_filter_bar.open.assert_called_once_with("src/diff.py")
    assert announced == ["src/diff.py"]
    w.reload.assert_called_once()


def test_clear_path_filter_announces_none_and_reloads(qtbot):
    w = _make_widget(qtbot)
    w.reload = MagicMock()
    w.set_path_filter("src/diff.py")
    announced: list[object] = []
    w.path_filter_changed.connect(announced.append)

    w.clear_path_filter()

    assert w._path_filter is None
    w._path_filter_bar.close_bar.assert_called_once()
    assert announced == [None]


def test_clear_path_filter_is_a_noop_when_not_filtered(qtbot):
    w = _make_widget(qtbot)
    w.reload = MagicMock()
    announced: list[object] = []
    w.path_filter_changed.connect(announced.append)

    w.clear_path_filter()

    assert announced == []
    w.reload.assert_not_called()


def test_entering_the_mode_drops_stale_paging_state(qtbot):
    """The previous listing's limit and pending scroll target mean nothing here."""
    w = _make_widget(qtbot)
    w.reload = MagicMock()
    w._reload_limit = 2000
    w._extra_tips = ["deadbeef"]
    w._pending_scroll_oid = "deadbeef"

    w.set_path_filter("src/diff.py")

    assert w._reload_limit == 50  # PAGE_SIZE
    assert w._extra_tips is None
    assert w._pending_scroll_oid is None


def test_switching_repo_clears_the_filter(qtbot):
    """A file history from the previous repo means nothing in the new one."""
    w = _make_widget(qtbot)
    w.reload = MagicMock()
    w.set_path_filter("src/diff.py")
    announced: list[object] = []
    w.path_filter_changed.connect(announced.append)

    w.set_buses(MagicMock(), MagicMock())

    assert w._path_filter is None
    assert announced == [None]


# ── What the filtered listing renders ────────────────────────────────────────


def _reload_done(w, commits, *, is_dirty=False, path_filter=None):
    w._on_reload_done(commits, [], [], is_dirty, "headoid", None, None, False, path_filter)


def test_filtered_listing_suppresses_the_lane_graph(qtbot):
    """Filtered commits are a sparse subset — lanes between them would be a lie."""
    w = _make_widget(qtbot)
    w._path_filter = "src/diff.py"
    _reload_done(w, [_make_commit("c1"), _make_commit("c2")], path_filter="src/diff.py")

    assert w._model.rowCount() == 2
    for row in range(2):
        lane_data = w._model.data(w._model.index(row, 0), LANE_ROLE)
        assert lane_data is None
        # No graph means the commit info starts hard against the left edge.
        assert row_graph_width(lane_data) == 0


def test_unfiltered_listing_still_draws_the_graph(qtbot):
    w = _make_widget(qtbot)
    _reload_done(w, [_make_commit("c1", parents=["c2"]), _make_commit("c2")])

    lane_data = w._model.data(w._model.index(0, 0), LANE_ROLE)
    assert lane_data is not None
    assert row_graph_width(lane_data) > 0


def test_filtered_listing_omits_the_uncommitted_changes_row(qtbot):
    """That synthetic row is anchored to HEAD's parents, which say nothing here."""
    w = _make_widget(qtbot)
    w._path_filter = "src/diff.py"
    _reload_done(w, [_make_commit("c1")], is_dirty=True, path_filter="src/diff.py")

    assert w._model.rowCount() == 1


def test_unfiltered_dirty_listing_keeps_the_uncommitted_changes_row(qtbot):
    w = _make_widget(qtbot)
    _reload_done(w, [_make_commit("c1")], is_dirty=True)

    assert w._model.rowCount() == 2


def test_reload_landing_with_a_stale_filter_is_discarded(qtbot):
    """The user changed the filter mid-flight; the in-flight page is the wrong one."""
    w = _make_widget(qtbot)
    w._path_filter = "src/other.py"
    w.reload = MagicMock()

    _reload_done(w, [_make_commit("c1")], path_filter="src/diff.py")

    w.reload.assert_called_once()
    assert w._model.rowCount() == 0
