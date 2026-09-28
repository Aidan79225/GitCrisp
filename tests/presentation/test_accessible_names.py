"""Every control that shows only an icon or a glyph must carry a spoken name.

A screen reader announces an icon-only button as nothing and "✕" as a
symbol name; these tests pin the names the app gives them instead.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QPushButton

from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle
from git_gui.presentation.widgets.graph import GraphWidget
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


def _spoken_name(widget) -> str:
    return QAccessible.queryAccessibleInterface(widget).text(QAccessible.Name)


@pytest.fixture
def graph(qtbot):
    queries = MagicMock()
    queries.get_commit_graph.execute.return_value = []
    queries.get_branches.execute.return_value = []
    queries.get_tags.execute.return_value = []
    queries.is_dirty.execute.return_value = False
    queries.get_head_oid.execute.return_value = "abc"
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = False
    w = GraphWidget(queries, MagicMock(), repo_store=repo_store)
    qtbot.addWidget(w)
    return w


def test_every_graph_button_has_a_word_for_a_name(graph):
    buttons = graph.findChildren(QPushButton)
    assert buttons
    for btn in buttons:
        name = _spoken_name(btn)
        assert any(c.isalpha() for c in name), f"unnamed button (tooltip {btn.toolTip()!r})"


def test_header_icon_buttons_are_named_by_action(graph):
    names = {_spoken_name(b) for b in graph._styled_buttons}
    assert {"Reload", "Push", "Pull", "Fetch all", "Stash", "First-parent history"} <= names


def test_commit_history_view_is_named(graph):
    assert _spoken_name(graph._view) == "Commit history"


def test_collapse_toggle_name_follows_its_state(qtbot):
    toggle = _CollapseToggle(expanded=True)
    qtbot.addWidget(toggle)
    assert _spoken_name(toggle) == "Collapse"
    toggle.setChecked(False)
    assert _spoken_name(toggle) == "Expand"


def test_working_tree_inputs_are_named(qtbot):
    w = WorkingTreeWidget(MagicMock(), MagicMock())
    qtbot.addWidget(w)
    assert _spoken_name(w._msg_edit) == "Commit message"
    assert _spoken_name(w._file_view) == "Changed files"
