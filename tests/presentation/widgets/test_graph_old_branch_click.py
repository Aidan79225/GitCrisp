"""Clicking a branch from long ago.

Three things went wrong at once, and they were one bug: the page came back
one row longer than the limit, because the clicked tip was pinned onto the
end of it. That extra row made a full page look like the end of history, so
the graph stopped loading more; it made `skip` step over a real commit; and
it put the tip on screen with none of the commits that descend from it, which
draws a branch merged long ago as a lane that never merges.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QWidget

from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import GraphModel
from git_gui.presentation.widgets.graph import MAX_RELOAD_LIMIT, PAGE_SIZE, GraphWidget


class _InlineThread:
    """Runs the worker where it was created.

    A real worker thread here outlives the test: it emits into a widget qtbot
    has already torn down, which on Windows is heap corruption rather than a
    failure. Nothing in these tests needs the work to be off the main thread.
    """

    def __init__(self, target=None, daemon=None, **kwargs) -> None:
        self._target = target

    def start(self) -> None:
        if self._target is not None:
            self._target()


@pytest.fixture
def inline_workers(monkeypatch):
    monkeypatch.setattr("git_gui.presentation.widgets.graph.threading.Thread", _InlineThread)


def _quiet_queries(w: GraphWidget) -> None:
    """Return values a finished load can be delivered with."""
    w._queries.get_commit_graph.execute.return_value = []
    w._queries.get_branches.execute.return_value = []
    w._queries.get_tags.execute.return_value = []
    w._queries.is_dirty.execute.return_value = False
    w._queries.get_head_oid.execute.return_value = ""
    w._queries.get_repo_state.execute.return_value = None
    w._queries.get_merge_head.execute.return_value = None


def _commits(n: int, prefix: str = "c") -> list[Commit]:
    return [
        Commit(
            oid=f"{prefix}{i}",
            message=f"commit {i}",
            author="A <a@example.com>",
            timestamp=datetime(2026, 1, 1),
            parents=[f"{prefix}{i + 1}"],
        )
        for i in range(n)
    ]


def _widget(qtbot) -> GraphWidget:
    """A GraphWidget without its heavy __init__ — the same shape the other
    graph tests use."""
    w = GraphWidget.__new__(GraphWidget)
    QWidget.__init__(w)
    w._queries = MagicMock()
    w._model = GraphModel([], {})
    w._loading = False
    w._loaded_count = 0
    w._has_more = False
    w._reload_limit = PAGE_SIZE
    w._pending_scroll_oid = None
    w._pending_merge_base = None
    w._pending_search = None
    w._extra_tips = None
    w._selected_oid = None
    w._scroll_anchor_oid = None
    w._first_parent = False
    w._path_filter = None
    w._path_filter_bar = MagicMock()
    w._path_filter_bar.follow.return_value = True
    w._stash_btn = MagicMock()
    w._view = MagicMock()
    w._search_bar = MagicMock()
    w._search_matches = []
    w._search_idx = -1
    qtbot.addWidget(w)
    return w


def _deliver(w: GraphWidget, commits: list[Commit]) -> None:
    """Hand the widget a finished reload, as the worker thread would."""
    w._on_reload_done(commits, [], [], False, "", None, None, w._first_parent, w._path_filter)


# ── The page that came back too long ─────────────────────────────────────────


def test_a_pinned_row_does_not_end_the_scroll(qtbot):
    """`len(page) == limit` was the test for "there may be more". A pinned tip
    made a full page count 51, which is not 50, so scrolling loaded nothing
    ever again."""
    w = _widget(qtbot)
    w._reload_limit = PAGE_SIZE

    _deliver(w, _commits(PAGE_SIZE) + _commits(1, prefix="pinned"))

    assert w._has_more is True


def test_a_pinned_row_is_not_counted_as_walked(qtbot):
    """`_loaded_count` becomes the next page's `skip`, and skip counts walker
    positions. Counting the pinned row would step over a real commit, which
    would then never appear at all."""
    w = _widget(qtbot)
    w._reload_limit = PAGE_SIZE

    _deliver(w, _commits(PAGE_SIZE) + _commits(1, prefix="pinned"))

    assert w._loaded_count == PAGE_SIZE


def test_a_short_page_still_ends_the_scroll(qtbot):
    """The end of history has to keep ending it."""
    w = _widget(qtbot)
    w._reload_limit = PAGE_SIZE

    _deliver(w, _commits(PAGE_SIZE - 10))

    assert w._has_more is False
    assert w._loaded_count == PAGE_SIZE - 10


# ── Pinning is the last resort, not the first ────────────────────────────────


def test_a_first_load_does_not_ask_for_a_pin(qtbot, inline_workers):
    """Pinning draws the tip with no descendants. While there is a deeper load
    left to try, the deeper load is the right answer."""
    w = _widget(qtbot)
    _quiet_queries(w)

    w.reload(extra_tips=["old"], limit=PAGE_SIZE)

    assert w._queries.get_commit_graph.execute.call_args.kwargs["pin_unreachable"] is False


def test_the_last_retry_asks_for_a_pin(qtbot, inline_workers):
    """At the cap there is nothing deeper to load, and a pinned row beats a
    click that appears to do nothing."""
    w = _widget(qtbot)
    _quiet_queries(w)

    w.reload(extra_tips=["old"], limit=MAX_RELOAD_LIMIT)

    assert w._queries.get_commit_graph.execute.call_args.kwargs["pin_unreachable"] is True


def test_scrolling_never_asks_for_a_pin(qtbot, inline_workers):
    """Every page would carry its own copy of the tip."""
    w = _widget(qtbot)
    _quiet_queries(w)
    w._extra_tips = ["old"]

    w._load_more()

    kwargs = w._queries.get_commit_graph.execute.call_args.kwargs
    assert kwargs.get("pin_unreachable", False) is False


# ── The tip keeps loading deeper until it is in its own place ────────────────


def test_an_unreached_tip_doubles_the_limit_instead_of_settling(qtbot):
    """This is what puts a merged branch back among its descendants: keep
    loading until the walk itself reaches it."""
    w = _widget(qtbot)
    w._reload_limit = PAGE_SIZE
    w._pending_scroll_oid = "old"
    w._pending_merge_base = None
    w.reload = MagicMock()

    _deliver(w, _commits(PAGE_SIZE))

    assert w.reload.call_args.kwargs["limit"] == PAGE_SIZE * 2
    assert w._pending_scroll_oid == "old", "still looking for it"


def test_the_tip_is_selected_once_the_walk_reaches_it(qtbot):
    w = _widget(qtbot)
    w._reload_limit = PAGE_SIZE
    w._pending_scroll_oid = "c3"
    w._pending_merge_base = None
    scrolled: list[str] = []
    w.scroll_to_oid = lambda oid, select=False: scrolled.append(oid)

    _deliver(w, _commits(PAGE_SIZE))

    assert scrolled == ["c3"]
    assert w._pending_scroll_oid is None


# ── The pinned row is not drawn twice ────────────────────────────────────────


def test_a_pinned_commit_is_not_appended_again_when_the_walk_reaches_it(qtbot):
    """Now that scrolling works past a pinned page, the walk eventually
    produces the very commit already pinned to the end of page one."""
    w = _widget(qtbot)
    _deliver(w, _commits(3) + _commits(1, prefix="pinned"))
    before = w._model.rowCount()

    w._on_append_done(_commits(1, prefix="pinned"), [], [], w._first_parent, w._path_filter)

    assert w._model.rowCount() == before
