"""Tests for GraphWidget synthetic commit row logic in _on_reload_done."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from git_gui.domain.entities import Commit, RepoState, RepoStateInfo, WORKING_TREE_OID
from git_gui.presentation.models.graph_model import GraphModel
from git_gui.presentation.widgets.graph import GraphWidget


def _make_commit(oid: str = "aaa", msg: str = "hello", parents: list[str] | None = None) -> Commit:
    return Commit(
        oid=oid, message=msg, author="A <a@a.com>",
        timestamp=datetime(2026, 1, 1), parents=parents or [],
    )


HEAD_OID = "deadbeefdeadbeef"


def _make_widget(qtbot) -> GraphWidget:
    """Create a minimal GraphWidget bypassing its full __init__."""
    w = GraphWidget.__new__(GraphWidget)
    QWidget.__init__(w)

    w._queries = object()  # truthy sentinel; _on_reload_done just checks `is None`
    w._model = GraphModel([], {})
    w._loading = False
    w._loaded_count = 0
    w._has_more = True
    w._reload_limit = 50
    w._pending_scroll_oid = None
    w._pending_search = None

    # _stash_btn is called with setVisible; use a simple mock
    w._stash_btn = MagicMock()

    # _update_column_widths touches the view/viewport — stub it out
    w._update_column_widths = lambda: None

    qtbot.addWidget(w)
    return w


def _state_info(state: RepoState) -> RepoStateInfo:
    return RepoStateInfo(state=state, head_branch="main")


# ── Tests ────────────────────────────────────────────────────────────────────


def test_dirty_clean_creates_uncommitted_changes_row(qtbot):
    w = _make_widget(qtbot)
    commits = [_make_commit("c1", parents=[])]

    w._on_reload_done(
        commits, [], [], True, HEAD_OID,
        _state_info(RepoState.CLEAN), None,
    )

    assert w._model.rowCount() == 2
    oid = w._model.data(w._model.index(0, 0), Qt.UserRole)
    assert oid == WORKING_TREE_OID
    info = w._model.data(w._model.index(0, 1), Qt.UserRole + 1)
    assert info.message == "Uncommitted Changes"

    # Check parents via the underlying commit object
    synthetic = w._model._commits[0]
    assert synthetic.parents == [HEAD_OID]


def test_dirty_merging_creates_merge_in_progress_row(qtbot):
    w = _make_widget(qtbot)
    merge_head = "abc123"
    commits = [_make_commit("c1")]

    w._on_reload_done(
        commits, [], [], True, HEAD_OID,
        _state_info(RepoState.MERGING), merge_head,
    )

    assert w._model.rowCount() == 2
    info = w._model.data(w._model.index(0, 1), Qt.UserRole + 1)
    assert info.message == "Merge in progress (conflicts)"

    synthetic = w._model._commits[0]
    assert synthetic.parents == [HEAD_OID, merge_head]


def test_dirty_rebasing_creates_rebase_in_progress_row(qtbot):
    w = _make_widget(qtbot)
    commits = [_make_commit("c1")]

    w._on_reload_done(
        commits, [], [], True, HEAD_OID,
        _state_info(RepoState.REBASING), None,
    )

    assert w._model.rowCount() == 2
    info = w._model.data(w._model.index(0, 1), Qt.UserRole + 1)
    assert info.message == "Rebase in progress"

    synthetic = w._model._commits[0]
    assert synthetic.parents == [HEAD_OID]


def test_not_dirty_no_synthetic_row(qtbot):
    w = _make_widget(qtbot)
    commits = [_make_commit("c1"), _make_commit("c2")]

    w._on_reload_done(
        commits, [], [], False, HEAD_OID,
        _state_info(RepoState.CLEAN), None,
    )

    assert w._model.rowCount() == 2  # exactly the real commits, no synthetic


def test_unborn_head_empty_graph(qtbot):
    w = _make_widget(qtbot)

    w._on_reload_done(
        [], [], [], False, "",
        _state_info(RepoState.CLEAN), None,
    )

    assert w._model.rowCount() == 0
