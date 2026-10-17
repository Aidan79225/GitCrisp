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


# ── The branch the user clicked ──────────────────────────────────────────────


def test_clicking_a_branch_below_the_page_leaves_its_tip_on_screen(graph, inline_workers):
    """The reload that loads the tip also restores the viewport saved before
    it. That restore must not undo the scroll to the tip the click asked for."""
    graph.resize(400, 300)
    graph.show()
    graph.reload()
    target = f"c{2 * PAGE_SIZE + 20}"
    graph._queries.get_merge_base.execute.return_value = target

    graph.reload_with_extra_tip(target)

    assert _current_oid(graph) == target
    viewport = graph._view.viewport().rect()
    assert viewport.intersects(graph._view.visualRect(graph._view.currentIndex()))


# ── A reload asked for while another load is in flight ───────────────────────


def _with_side_branch(graph: GraphWidget) -> None:
    """`side` forks from c5. The walk reaches it only when it is pushed as a tip."""
    main = _chain(10)
    side = [
        Commit(
            oid="side", message="side", author="A", timestamp=datetime(2026, 1, 2), parents=["c5"]
        )
    ]

    def walk(limit, skip=0, extra_tips=None, **_):
        commits = side + main if "side" in (extra_tips or []) else main
        return commits[skip : skip + limit]

    graph._queries.get_commit_graph.execute.side_effect = walk
    graph._queries.get_head_oid.execute.return_value = "c0"
    graph._queries.get_merge_base.execute.return_value = "c5"


def _finish_all(held: _HeldWorkers) -> None:
    while held.waiting:
        held.finish_next()


def test_a_branch_clicked_while_a_load_is_in_flight_is_loaded_and_selected(graph, held_workers):
    _with_side_branch(graph)
    graph.reload()  # the focus-return reload, still running

    graph.reload_with_extra_tip("side")
    _finish_all(held_workers)

    assert _current_oid(graph) == "side"


def test_a_commit_made_while_a_load_is_in_flight_shows_up(graph, held_workers):
    before = _chain(5)
    new = Commit(
        oid="new", message="new", author="A", timestamp=datetime(2026, 1, 3), parents=["c0"]
    )
    # The load in flight read the repo before the commit; any later one after.
    graph._queries.get_commit_graph.execute.side_effect = [before, [new, *before]]
    graph.reload()

    graph.reload()  # the post-commit reload
    _finish_all(held_workers)

    assert graph._model.data(graph._model.index(0, 0), OID_ROLE) == "new"


def test_unticking_follow_while_the_file_history_loads_reloads_without_follow(graph, held_workers):
    graph._queries.get_file_history.execute.return_value = _chain(3)
    graph.set_path_filter("src/app.py")  # starts the load with follow on

    graph._path_filter_bar._follow.setChecked(False)
    _finish_all(held_workers)

    assert graph._queries.get_file_history.execute.call_args.kwargs["follow"] is False


def test_typing_on_while_a_search_loads_the_history_does_not_restart_the_load(graph, held_workers):
    graph._search_bar.input_widget.setText("commit 1")
    graph._search_bar.input_widget.setText("commit 12")
    _finish_all(held_workers)

    assert graph._queries.get_commit_graph.execute.call_count == 1
    assert _current_oid(graph) == "c12"


# ── Search ───────────────────────────────────────────────────────────────────


def test_closing_the_search_before_its_history_loads_cancels_the_jump(graph, qtbot, held_workers):
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")

    graph._close_search()
    with qtbot.assertNotEmitted(graph.commit_selected):
        _finish_all(held_workers)

    assert _current_oid(graph) is None


def test_clearing_the_search_text_before_its_history_loads_cancels_the_jump(
    graph, qtbot, held_workers
):
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")

    graph._search_bar.input_widget.clear()
    with qtbot.assertNotEmitted(graph.commit_selected):
        _finish_all(held_workers)

    assert _current_oid(graph) is None
