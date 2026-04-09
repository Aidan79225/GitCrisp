"""Tests for the merge/rebase section of GraphWidget._show_context_menu.

We exercise _add_merge_rebase_section directly with a fake QueryBus to avoid
needing a fully-initialised GraphWidget.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
import pytest
from PySide6.QtWidgets import QMenu

from git_gui.domain.entities import RepoState, RepoStateInfo
from git_gui.presentation.widgets.graph import GraphWidget


@dataclass
class _FakeQuery:
    fn: Callable
    def execute(self, *args, **kwargs):
        return self.fn(*args, **kwargs)


class _FakeQueryBus:
    def __init__(self, *, state: RepoStateInfo, head_oid: str | None,
                 is_ancestor: Callable[[str, str], bool] = lambda a, d: False):
        self.get_repo_state = _FakeQuery(lambda: state)
        self.get_head_oid = _FakeQuery(lambda: head_oid)
        self.is_ancestor = _FakeQuery(is_ancestor)


class _Stub(GraphWidget.__mro__[0]):  # type: ignore[misc]
    pass


def _make_widget_with_queries(qtbot, queries) -> GraphWidget:
    # GraphWidget.__init__ does a lot — bypass it for these unit tests.
    w = GraphWidget.__new__(GraphWidget)
    w._queries = queries
    # GraphWidget inherits from QWidget; QObject signal infrastructure requires
    # the C++ part to exist. Initialise the QWidget base only.
    from PySide6.QtWidgets import QWidget
    QWidget.__init__(w)
    qtbot.addWidget(w)
    return w


def _labels(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if a.text()]


def _enabled(menu: QMenu, label: str) -> bool:
    for a in menu.actions():
        if a.text() == label:
            return a.isEnabled()
    raise AssertionError(f"action {label!r} not in menu")


def _tooltip(menu: QMenu, label: str) -> str:
    for a in menu.actions():
        if a.text() == label:
            return a.toolTip()
    raise AssertionError(f"action {label!r} not in menu")


def test_detached_head_disables_everything(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.DETACHED_HEAD, head_branch=None),
        head_oid="aaaaaaaaaaaa",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    menu.setToolTipsVisible(True)
    w._add_merge_rebase_section(menu, oid="bbbbbbbbbbbb", branches_on_commit=["feature"])

    assert _enabled(menu, "Merge feature into HEAD") is False
    assert "detached" in _tooltip(menu, "Merge feature into HEAD").lower()


def test_merging_state_disables_everything(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.MERGING, head_branch="main"),
        head_oid="aaaaaaaaaaaa",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    menu.setToolTipsVisible(True)
    w._add_merge_rebase_section(menu, oid="bbbbbbbbbbbb", branches_on_commit=["feature"])

    assert _enabled(menu, "Merge feature into main") is False
    assert "MERGING" in _tooltip(menu, "Merge feature into main")


def test_head_commit_with_no_other_branches_hides_section(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="aaaaaaaaaaaa",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    w._add_merge_rebase_section(menu, oid="aaaaaaaaaaaa", branches_on_commit=[])

    assert _labels(menu) == []  # nothing added


def test_ancestor_branch_merge_disabled_with_already_up_to_date(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="head1234567",
        is_ancestor=lambda a, d: a == "anc12345678" and d == "head1234567",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    menu.setToolTipsVisible(True)
    w._add_merge_rebase_section(menu, oid="anc12345678", branches_on_commit=["old-branch"])

    assert _enabled(menu, "Merge old-branch into main") is False
    assert _tooltip(menu, "Merge old-branch into main") == "Already up to date"
    # Rebase still allowed
    assert _enabled(menu, "Rebase main onto old-branch") is True


def test_normal_commit_emits_signals(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="head1234567",
    )
    w = _make_widget_with_queries(qtbot, queries)

    received_branch_merge: list[str] = []
    received_commit_merge: list[str] = []
    received_branch_rebase: list[str] = []
    received_commit_rebase: list[str] = []
    w.merge_branch_requested.connect(received_branch_merge.append)
    w.merge_commit_requested.connect(received_commit_merge.append)
    w.rebase_onto_branch_requested.connect(received_branch_rebase.append)
    w.rebase_onto_commit_requested.connect(received_commit_rebase.append)

    menu = QMenu()
    w._add_merge_rebase_section(menu, oid="newcommit12", branches_on_commit=["feature"])

    # Trigger each action
    for a in menu.actions():
        if a.text() == "Merge feature into main":
            a.trigger()
        elif a.text() == "Merge commit newcomm into main":
            a.trigger()
        elif a.text() == "Rebase main onto feature":
            a.trigger()
        elif a.text() == "Rebase main onto commit newcomm":
            a.trigger()

    assert received_branch_merge == ["feature"]
    assert received_commit_merge == ["newcommit12"]
    assert received_branch_rebase == ["feature"]
    assert received_commit_rebase == ["newcommit12"]


def test_multiple_branches_produce_one_action_each(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="head1234567",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    w._add_merge_rebase_section(menu, oid="other123456", branches_on_commit=["a", "b"])

    labels = _labels(menu)
    assert "Merge a into main" in labels
    assert "Merge b into main" in labels
    assert "Rebase main onto a" in labels
    assert "Rebase main onto b" in labels
