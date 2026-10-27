"""The real GraphWidget's context menu on one commit row."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QPoint
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from git_gui.domain.entities import Branch, Commit, Remote, RepoState, RepoStateInfo
from git_gui.presentation.widgets.graph import GraphWidget
from tests.presentation.widgets.graph_helpers import graph_widget

ROW_OID = "c" * 40


def open_context_menu(
    qtbot, branches: list[Branch], queries: MagicMock | None = None
) -> tuple[GraphWidget, QMenu]:
    """Right-click a commit that `branches` point at; return the widget and its menu.

    `queries` answers the menu's own reads; by default, queries_listing(branches).
    The menu is read instead of shown: patching QMenu.exec does not stop the
    C++ modal from opening, so graph's QMenu is swapped for a subclass whose
    exec returns at once (the same approach as test_sidebar_signals).
    """
    widget = graph_widget(qtbot, queries or queries_listing(branches))
    commit = Commit(ROW_OID, "subject", "T", datetime(2026, 1, 1), [])
    widget._model.reload(
        [commit],
        {ROW_OID: [b.name for b in branches]},
        remote_branches=frozenset(b.name for b in branches if b.is_remote),
    )
    widget._view.indexAt = MagicMock(return_value=widget._model.index(0, 0))

    built: list[QMenu] = []

    class _UnshownMenu(QMenu):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            built.append(self)

        def exec(self, *_args, **_kwargs):
            return None

    with patch("git_gui.presentation.widgets.graph.QMenu", _UnshownMenu):
        widget._show_context_menu(QPoint(0, 0))
    return widget, built[0]


def find_action(menu: QMenu, text: str, submenu: str | None = None) -> QAction:
    """The action labelled `text`, at the top level or inside `submenu`."""
    actions = menu.actions()
    if submenu is not None:
        actions = next(a.menu() for a in actions if a.menu() and a.text() == submenu).actions()
    return next(a for a in actions if a.text() == text)


def queries_listing(branches: list[Branch]) -> MagicMock:
    """A query bus whose repo holds `branches` and the one remote 'origin'."""
    queries = MagicMock()
    queries.get_branches.execute.return_value = branches
    queries.list_remotes.execute.return_value = [Remote("origin", "u", "u")]
    queries.get_repo_state.execute.return_value = RepoStateInfo(RepoState.CLEAN, "main")
    queries.get_head_oid.execute.return_value = ROW_OID
    queries.is_ancestor.execute.return_value = False
    return queries
