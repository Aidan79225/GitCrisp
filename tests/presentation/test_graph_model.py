from datetime import datetime
from git_gui.domain.entities import Branch, Commit
from git_gui.presentation.models.graph_model import GraphModel
from PySide6.QtCore import Qt


def _make_commit(oid="abc", msg="Initial commit"):
    return Commit(oid=oid, message=msg, author="Alice <a@a.com>",
                  timestamp=datetime(2026, 1, 1), parents=[])


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


def test_refs_column_shows_branch_names(qtbot):
    commits = [_make_commit("abc")]
    refs = {"abc": ["main", "origin/main"]}
    model = GraphModel(commits, refs)
    idx = model.index(0, 1)
    text = model.data(idx, Qt.DisplayRole)
    assert "main" in text


def test_invalid_index_returns_none(qtbot):
    model = GraphModel([], {})
    assert model.data(model.index(99, 0), Qt.DisplayRole) is None
