from datetime import datetime

from PySide6.QtCore import Qt

from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import CommitInfo, GraphModel, LaneData


def _make_commit(oid="abc", msg="Initial commit", parents=None):
    return Commit(
        oid=oid,
        message=msg,
        author="Alice <a@a.com>",
        timestamp=datetime(2026, 1, 1, 14, 32),
        parents=parents or [],
    )


def test_row_count_matches_commits(qtbot):
    commits = [_make_commit("a"), _make_commit("b"), _make_commit("c")]
    model = GraphModel(commits, {})
    assert model.rowCount() == 3


def test_column_count(qtbot):
    model = GraphModel([], {})
    assert model.columnCount() == 2  # graph, info


def test_user_role_returns_oid(qtbot):
    model = GraphModel([_make_commit("deadbeef")], {})
    idx = model.index(0, 0)
    assert model.data(idx, Qt.UserRole) == "deadbeef"


def test_commit_info_is_instance(qtbot):
    model = GraphModel([_make_commit("abc")], {})
    idx = model.index(0, 1)
    info = model.data(idx, Qt.UserRole + 1)
    assert isinstance(info, CommitInfo)


def test_commit_info_message(qtbot):
    model = GraphModel([_make_commit("a", "feat: thing\n\nBody text")], {})
    idx = model.index(0, 1)
    info = model.data(idx, Qt.UserRole + 1)
    assert info.message == "feat: thing"


def test_commit_info_author(qtbot):
    model = GraphModel([_make_commit()], {})
    idx = model.index(0, 1)
    info = model.data(idx, Qt.UserRole + 1)
    assert info.author == "Alice <a@a.com>"


def test_commit_info_timestamp(qtbot):
    model = GraphModel([_make_commit()], {})
    idx = model.index(0, 1)
    info = model.data(idx, Qt.UserRole + 1)
    assert "2026-01-01" in info.timestamp


def test_commit_info_short_oid(qtbot):
    commits = [_make_commit("abcdef1234")]
    model = GraphModel(commits, {})
    idx = model.index(0, 1)
    info = model.data(idx, Qt.UserRole + 1)
    assert info.short_oid == "abcdef12"


def test_commit_info_branch_names(qtbot):
    commits = [_make_commit("abc")]
    refs = {"abc": ["main", "origin/main"]}
    model = GraphModel(commits, refs)
    idx = model.index(0, 1)
    info = model.data(idx, Qt.UserRole + 1)
    assert info.branch_names == ["main", "origin/main"]


def test_lane_data_is_instance(qtbot):
    model = GraphModel([_make_commit("a")], {})
    idx = model.index(0, 0)
    ld = model.data(idx, Qt.UserRole + 1)
    assert isinstance(ld, LaneData)


def test_linear_history_all_lane_zero(qtbot):
    commits = [
        _make_commit("c", parents=["b"]),
        _make_commit("b", parents=["a"]),
        _make_commit("a", parents=[]),
    ]
    model = GraphModel(commits, {})
    for row in range(3):
        ld = model.data(model.index(row, 0), Qt.UserRole + 1)
        assert ld.lane == 0, f"row {row} expected lane 0, got {ld.lane}"


def test_branch_tip_opens_second_lane(qtbot):
    commits = [
        _make_commit("b1", parents=["base"]),
        _make_commit("b2", parents=["base"]),
        _make_commit("base", parents=[]),
    ]
    model = GraphModel(commits, {})
    ld0 = model.data(model.index(0, 0), Qt.UserRole + 1)
    ld1 = model.data(model.index(1, 0), Qt.UserRole + 1)
    assert ld0.lane == 0
    assert ld1.lane == 1


def test_merge_commit_has_diagonal_edge(qtbot):
    commits = [
        _make_commit("m", parents=["p1", "p2"]),
        _make_commit("p1", parents=[]),
        _make_commit("p2", parents=[]),
    ]
    model = GraphModel(commits, {})
    ld = model.data(model.index(0, 0), Qt.UserRole + 1)
    from_to = [(e[0], e[1]) for e in ld.edges_out]
    assert (0, 1) in from_to


def test_invalid_index_returns_none(qtbot):
    model = GraphModel([], {})
    assert model.data(model.index(99, 0), Qt.DisplayRole) is None


def test_badge_color_head():
    from git_gui.presentation.widgets.ref_badge_delegate import _badge_color

    color = _badge_color("HEAD")
    assert color.name().lower() == "#238636"


def test_badge_color_head_arrow():
    from git_gui.presentation.widgets.ref_badge_delegate import _badge_color

    color = _badge_color("HEAD -> main")
    assert color.name().lower() == "#238636"


def test_badge_color_remote():
    from git_gui.presentation.widgets.ref_badge_delegate import _badge_color

    color = _badge_color("origin/main")
    assert color.name().lower() == "#1f4287"


def test_badge_color_local():
    from git_gui.presentation.widgets.ref_badge_delegate import _badge_color

    color = _badge_color("main")
    assert color.name().lower() == "#0d6efd"


# ── First-parent mode: side parents are ignored ──────────────────────────────


def test_compute_lanes_first_parent_collapses_merge_to_single_lane(qtbot):
    """In first_parent mode, a merge commit whose second parent isn't in the
    listing must NOT open an extra lane or draw a diagonal outgoing edge —
    otherwise the graph paints a stub line to a ghost lane."""
    from git_gui.presentation.models.graph_model import _compute_lanes

    # M (merge of feature into master, second parent D not in list)
    # B (master, M's first parent)
    # A (initial)
    commits = [
        _make_commit("M", "Merge", parents=["B", "D"]),
        _make_commit("B", "B", parents=["A"]),
        _make_commit("A", "A", parents=[]),
    ]
    lanes = _compute_lanes(commits, first_parent=True)
    # Every commit sits in lane 0 and never spawns a side lane.
    assert all(ld.lane == 0 for ld in lanes), lanes
    assert all(ld.n_lanes == 1 for ld in lanes), lanes
    # Merge commit emits exactly one outgoing edge (to its first parent's lane).
    assert lanes[0].edges_out == [(0, 0, lanes[0].color_idx)]


def test_compute_lanes_full_mode_keeps_side_lane(qtbot):
    """Sanity check: in full mode (the default), the same merge layout DOES
    spawn an extra lane and a diagonal edge, so the toggle is what's making
    the difference."""
    from git_gui.presentation.models.graph_model import _compute_lanes

    commits = [
        _make_commit("M", "Merge", parents=["B", "D"]),
        _make_commit("B", "B", parents=["A"]),
        _make_commit("A", "A", parents=[]),
    ]
    lanes = _compute_lanes(commits, first_parent=False)
    # M's row knows it has 2 edges_out (one straight, one diagonal to D's lane).
    assert len(lanes[0].edges_out) == 2
    assert lanes[0].n_lanes >= 2


def test_graph_model_reload_first_parent_kwarg_recomputes_lanes(qtbot):
    """GraphModel.reload(..., first_parent=True) must store the flag and
    apply it on subsequent append() calls so paginated rows stay consistent
    with the first page."""
    model = GraphModel([], {})
    commits = [
        _make_commit("M", "Merge", parents=["B", "D"]),
        _make_commit("B", "B", parents=["A"]),
    ]
    model.reload(commits, {}, first_parent=True)
    # Toggle persisted; the lane data agrees.
    assert model._first_parent is True
    assert all(ld.lane == 0 for ld in model._lane_data)
    # Append uses the stored flag — the appended row must also be single-lane.
    model.append([_make_commit("A", "A", parents=[])], {})
    assert all(ld.lane == 0 for ld in model._lane_data)


def test_max_lanes_empty_model_is_one(qtbot):
    """An empty model still reports one lane so the column never collapses."""
    assert GraphModel([], {}).max_lanes() == 1


def test_max_lanes_linear_history_is_one(qtbot):
    commits = [
        _make_commit("c", "C", parents=["b"]),
        _make_commit("b", "B", parents=["a"]),
        _make_commit("a", "A", parents=[]),
    ]
    assert GraphModel(commits, {}).max_lanes() == 1


def test_max_lanes_reports_widest_row(qtbot):
    """A merge that opens a side lane widens the reported lane count."""
    commits = [
        _make_commit("M", "Merge", parents=["B", "D"]),
        _make_commit("B", "B", parents=["A"]),
        _make_commit("A", "A", parents=[]),
    ]
    model = GraphModel(commits, {})
    assert model.max_lanes() == 2
    # first-parent mode collapses the side lane back to a single column
    model.reload(commits, {}, first_parent=True)
    assert model.max_lanes() == 1
