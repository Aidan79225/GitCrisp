from datetime import datetime
from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import CommitInfo, GraphModel, LaneData
from PySide6.QtCore import Qt


def _make_commit(oid="abc", msg="Initial commit", parents=None):
    return Commit(oid=oid, message=msg, author="Alice <a@a.com>",
                  timestamp=datetime(2026, 1, 1, 14, 32), parents=parents or [])


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
