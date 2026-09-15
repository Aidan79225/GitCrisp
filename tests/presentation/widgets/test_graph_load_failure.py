"""A graph load that fails must not leave the graph unable to load again.

Deleting the repo on screen from outside GitCrisp made the next background load
raise in its worker thread. The worker died before handing a result back, so
`_loading` stayed set and every later `reload()` returned at its guard — the
graph kept showing the deleted repo, even after switching to another one.
"""

from __future__ import annotations

import threading
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from git_gui.domain.entities import Commit
from git_gui.presentation.widgets.graph import GraphWidget


def _commit(oid: str) -> Commit:
    return Commit(oid=oid, message=oid, author="t", timestamp=datetime(2026, 1, 1), parents=[])


def _make_queries(commits: list[Commit] | None = None) -> MagicMock:
    q = MagicMock()
    q.get_commit_graph.execute.return_value = commits or []
    q.get_branches.execute.return_value = []
    q.get_tags.execute.return_value = []
    q.is_dirty.execute.return_value = False
    q.get_head_oid.execute.return_value = ""
    q.get_repo_state.execute.return_value = MagicMock(head_branch=None)
    q.get_merge_head.execute.return_value = None
    return q


@pytest.fixture
def graph(qtbot):
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = False
    widget = GraphWidget(None, MagicMock(), repo_store=repo_store)
    qtbot.addWidget(widget)
    return widget


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_failed_reload_does_not_block_the_next_one(graph, qtbot):
    queries = _make_queries([_commit("a1")])
    queries.get_commit_graph.execute.side_effect = [
        RuntimeError("head reference does not exist"),
        [_commit("a1")],
    ]
    graph.set_buses(queries, MagicMock())  # first load fails
    qtbot.waitUntil(lambda: not graph._loading, timeout=2000)

    graph.reload()

    qtbot.waitUntil(lambda: graph._model.rowCount() == 1, timeout=2000)
    assert queries.get_commit_graph.execute.call_count == 2


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_failed_page_load_does_not_block_reloads(graph, qtbot):
    queries = _make_queries([_commit("a1")])
    graph.set_buses(queries, MagicMock())
    qtbot.waitUntil(lambda: graph._model.rowCount() == 1, timeout=2000)

    queries.get_commit_graph.execute.side_effect = RuntimeError("gone")
    graph._load_more()

    qtbot.waitUntil(lambda: not graph._loading, timeout=2000)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_switching_repos_loads_the_new_repo_after_a_failed_load(graph, qtbot):
    deleted = _make_queries()
    deleted.get_commit_graph.execute.side_effect = RuntimeError("head reference does not exist")
    graph.set_buses(deleted, MagicMock())
    qtbot.wait(50)  # let the failing worker run

    other = _make_queries([_commit("b1"), _commit("b2")])
    graph.set_buses(other, MagicMock())

    qtbot.waitUntil(lambda: graph._model.rowCount() == 2, timeout=2000)
    assert not graph._loading


def test_a_late_result_from_the_previous_repo_is_dropped(graph, qtbot):
    """Switching repos starts the new repo's load at once, so the old repo's
    load can still land afterwards — and must not paint over the new one."""
    release = threading.Event()

    def _slow_old_repo(**_kwargs):
        release.wait(2)
        return [_commit("old1"), _commit("old2"), _commit("old3")]

    old = _make_queries()
    old.get_commit_graph.execute.side_effect = _slow_old_repo
    graph.set_buses(old, MagicMock())  # in flight, blocked

    new = _make_queries([_commit("new1")])
    graph.set_buses(new, MagicMock())
    qtbot.waitUntil(lambda: graph._model.rowCount() == 1, timeout=2000)

    release.set()
    qtbot.wait(200)  # the old load finishes and hands its result back

    assert graph._model.rowCount() == 1
