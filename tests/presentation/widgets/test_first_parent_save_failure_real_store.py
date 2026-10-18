"""The graph reports a first-parent choice the real repo store could not save.

The graph's own tests fake a store whose save() raises. This pins that the
shipped JsonRepoStore fails the same way, so the report is not dead code.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.widgets.graph import GraphWidget


def _empty_queries() -> MagicMock:
    queries = MagicMock()
    queries.get_commit_graph.execute.return_value = []
    queries.get_branches.execute.return_value = []
    queries.get_tags.execute.return_value = []
    queries.is_dirty.execute.return_value = False
    queries.get_head_oid.execute.return_value = ""
    queries.get_repo_state.execute.return_value = MagicMock(head_branch=None)
    queries.get_merge_head.execute.return_value = None
    return queries


def test_a_first_parent_choice_the_repo_file_cannot_take_is_reported(qtbot, tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("", encoding="utf-8")
    store = JsonRepoStore(blocker / "repos.json")
    store.load()
    graph = GraphWidget(_empty_queries(), MagicMock(), repo_store=store)
    qtbot.addWidget(graph)
    graph.set_repo_path("/repo/a")

    with qtbot.waitSignal(graph.setting_save_failed, timeout=1000):
        graph._first_parent_btn.setChecked(True)
