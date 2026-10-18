"""The graph tells its rows which branch names are remote-tracking.

A local branch can have a slash in its name (``feature/login``) just as
``origin/main`` does, so the badge colour has to come from the branch list,
not from the name.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from git_gui.domain.entities import Branch, Commit
from git_gui.presentation.models.graph_model import INFO_ROLE
from git_gui.presentation.widgets.graph import GraphWidget

TIP = "a" * 40


def _graph_after_reload(qtbot, branches: list[Branch]) -> GraphWidget:
    w = GraphWidget(MagicMock(), MagicMock(), repo_store=MagicMock())
    qtbot.addWidget(w)
    commit = Commit(oid=TIP, message="m", author="A", timestamp=datetime(2026, 1, 1), parents=[])
    w._on_reload_done([commit], branches, [], False, TIP, None, None, False)
    return w


def test_a_reload_tells_the_rows_which_branches_are_remote(qtbot):
    w = _graph_after_reload(
        qtbot,
        [
            Branch(name="feature/login", is_remote=False, is_head=False, target_oid=TIP),
            Branch(name="origin/main", is_remote=True, is_head=False, target_oid=TIP),
        ],
    )

    info = w._model.data(w._model.index(0, 0), INFO_ROLE)

    assert info.remote_branches == frozenset({"origin/main"})
