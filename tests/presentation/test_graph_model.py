from datetime import datetime
from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import GraphModel, LaneData
from PySide6.QtCore import Qt


def _make_commit(oid="abc", msg="Initial commit", parents=None):
    return Commit(oid=oid, message=msg, author="Alice <a@a.com>",
                  timestamp=datetime(2026, 1, 1), parents=parents or [])


def test_row_count_matches_commits(qtbot):
    commits = [_make_commit("a"), _make_commit("b"), _make_commit("c")]
    model = GraphModel(commits, {})
    assert model.rowCount() == 3


def test_column_count(qtbot):
    model = GraphModel([], {})
    assert model.columnCount() == 5  # graph, refs, message, author, date


def test_message_column(qtbot):
    model = GraphModel([_make_commit("a", "feat: thing\n\nBody text")], {})
    idx = model.index(0, 2)
    assert model.data(idx, Qt.DisplayRole) == "feat: thing"


def test_author_column(qtbot):
    model = GraphModel([_make_commit()], {})
    idx = model.index(0, 3)
    assert model.data(idx, Qt.DisplayRole) == "Alice <a@a.com>"


def test_date_column(qtbot):
    model = GraphModel([_make_commit()], {})
    idx = model.index(0, 4)
    assert "2026-01-01" in model.data(idx, Qt.DisplayRole)


def test_user_role_returns_oid(qtbot):
    model = GraphModel([_make_commit("deadbeef")], {})
    idx = model.index(0, 0)
    assert model.data(idx, Qt.UserRole) == "deadbeef"


def test_hash_column_shows_short_oid(qtbot):
    commits = [_make_commit("abcdef1234")]
    model = GraphModel(commits, {})
    idx = model.index(0, 1)
    assert model.data(idx, Qt.DisplayRole) == "abcdef12"


def test_message_userrole_returns_branch_names(qtbot):
    commits = [_make_commit("abc")]
    refs = {"abc": ["main", "origin/main"]}
    model = GraphModel(commits, refs)
    idx = model.index(0, 2)
    names = model.data(idx, Qt.UserRole + 1)
    assert names == ["main", "origin/main"]


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
    # b1 takes lane 0 (first seen), b2 gets lane 1 (lane 0 is waiting for "base")
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
    # "m" merges p1 (first parent, lane 0) and p2 (second parent, opens lane 1)
    # edges_out for row 0 must include (0, 1, ...) diagonal
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
