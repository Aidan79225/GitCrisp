"""What a reload keeps, and what it must not throw away.

Auto-reloads run all the time — on focus return, on every change under .git,
after every operation — so anything a reload loses, the user loses on every
alt-tab: the pages they scrolled through, the row they selected, the branch
they just clicked.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import OID_ROLE
from git_gui.presentation.widgets.graph import PAGE_SIZE, GraphWidget


def _chain(n: int, prefix: str = "c") -> list[Commit]:
    """A linear history, newest first: c0's parent is c1, and so on."""
    return [
        Commit(
            oid=f"{prefix}{i}",
            message=f"commit {i}",
            author="A <a@example.com>",
            timestamp=datetime(2026, 1, 1),
            parents=[f"{prefix}{i + 1}"] if i + 1 < n else [],
        )
        for i in range(n)
    ]


class _InlineThread:
    """Runs the worker where it was created, so its result lands at once."""

    def __init__(self, target=None, daemon=None, **kwargs) -> None:
        self._target = target

    def start(self) -> None:
        if self._target is not None:
            self._target()


class _HeldWorkers:
    """Holds each worker until the test lets it finish — a load in flight."""

    def __init__(self) -> None:
        self.waiting: list[Callable[[], None]] = []

    def thread(self, target=None, daemon=None, **kwargs) -> _HeldWorkers:
        self.waiting.append(target)
        return self

    def start(self) -> None:
        pass

    def finish_next(self) -> None:
        self.waiting.pop(0)()


@pytest.fixture
def inline_workers(monkeypatch):
    monkeypatch.setattr("git_gui.presentation.widgets.graph.threading.Thread", _InlineThread)


@pytest.fixture
def held_workers(monkeypatch) -> _HeldWorkers:
    held = _HeldWorkers()
    monkeypatch.setattr("git_gui.presentation.widgets.graph.threading.Thread", held.thread)
    return held


def _queries(history: list[Commit]) -> MagicMock:
    """A query bus over a linear history that pages like the real walk."""
    q = MagicMock()
    q.get_commit_graph.execute.side_effect = lambda limit, skip=0, **_: history[skip : skip + limit]
    q.get_branches.execute.return_value = []
    q.get_tags.execute.return_value = []
    q.is_dirty.execute.return_value = False
    q.get_head_oid.execute.return_value = history[0].oid
    q.get_repo_state.execute.return_value = None
    q.get_merge_head.execute.return_value = None
    return q


@pytest.fixture
def graph(qtbot) -> GraphWidget:
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = False
    widget = GraphWidget(_queries(_chain(3 * PAGE_SIZE)), MagicMock(), repo_store=repo_store)
    qtbot.addWidget(widget)
    return widget


def _current_oid(graph: GraphWidget) -> str | None:
    return graph._model.data(graph._view.currentIndex(), OID_ROLE)


# ── Pages the user scrolled through ──────────────────────────────────────────


def test_a_bare_reload_keeps_every_page_the_user_scrolled_through(graph, inline_workers):
    graph.reload()
    graph._load_more()
    assert graph._model.rowCount() == 2 * PAGE_SIZE

    graph.reload()  # the focus-return auto-reload

    assert graph._model.rowCount() == 2 * PAGE_SIZE


def test_a_bare_reload_keeps_the_highlight_on_a_row_from_a_later_page(graph, inline_workers):
    graph.reload()
    graph._load_more()
    graph._view.setCurrentIndex(graph._model.index(PAGE_SIZE + 30, 0))

    graph.reload()

    assert _current_oid(graph) == f"c{PAGE_SIZE + 30}"
