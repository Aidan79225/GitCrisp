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
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from git_gui.domain.entities import (
    WORKING_TREE_OID,
    Commit,
    FileDelta,
    FileStatus,
    RepoState,
    RepoStateInfo,
    StagingState,
    Tag,
)
from git_gui.presentation.models.graph_model import INFO_ROLE, LANE_ROLE, OID_ROLE
from git_gui.presentation.widgets.graph import PAGE_SIZE, GraphWidget
from tests.presentation.widgets.graph_helpers import InlineThread, fake_graph_threads


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
    fake_graph_threads(monkeypatch, InlineThread)


@pytest.fixture
def held_workers(monkeypatch) -> _HeldWorkers:
    held = _HeldWorkers()
    fake_graph_threads(monkeypatch, held.thread)
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


def _with_side_branch(graph: GraphWidget, length: int = 10) -> None:
    """`side` forks from c5 of a `length`-commit chain. The walk reaches it
    only when it is pushed as a tip."""
    main = _chain(length)
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


def _last_graph_limit(graph: GraphWidget) -> int:
    return graph._queries.get_commit_graph.execute.call_args.kwargs["limit"]


def test_auto_reloads_after_a_search_closes_go_back_to_a_page(graph, inline_workers):
    """A search loads the whole history to look through it. Kept afterwards,
    that size made every alt-tab walk and lay out the entire history."""
    graph.reload()
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")
    graph._close_search()

    graph.reload()

    assert _last_graph_limit(graph) == PAGE_SIZE


def test_auto_reloads_after_a_search_closes_keep_the_pages_scrolled_before_it(
    graph, inline_workers
):
    graph.reload()
    graph._load_more()
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")
    graph._close_search()

    graph.reload()

    assert _last_graph_limit(graph) == 2 * PAGE_SIZE


def test_closing_the_search_while_its_history_loads_loads_a_page_instead(graph, held_workers):
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")

    graph._close_search()
    _finish_all(held_workers)

    assert _last_graph_limit(graph) == PAGE_SIZE
    assert graph._model.rowCount() == PAGE_SIZE


def test_the_next_match_is_still_a_match_after_a_reload_shifts_the_rows(graph, inline_workers):
    """Editing a file adds the 'Uncommitted Changes' row on top, moving every
    commit down one row. Matches kept as rows then pointed at their neighbours."""
    graph.reload()
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")  # c12, then c120…c129
    assert _current_oid(graph) == "c12"

    graph._queries.is_dirty.execute.return_value = True
    graph.reload()
    graph._on_search_navigate(1)

    assert _current_oid(graph) == "c120"


# ── The selected row and the diff pane ───────────────────────────────────────


def _select_row(graph: GraphWidget, row: int) -> None:
    graph._view.setCurrentIndex(graph._model.index(row, 0))


def test_a_commit_clicked_again_after_the_selection_was_cleared_is_shown_again(
    graph, qtbot, inline_workers
):
    """Clicking a stash clears the graph's selection and shows the stash in
    the diff pane; clicking the commit again has to bring it back."""
    graph.reload()
    _select_row(graph, 2)

    graph.clear_selection()
    with qtbot.waitSignal(graph.commit_selected, timeout=1000) as shown:
        _select_row(graph, 2)

    assert shown.args == ["c2"]


def test_the_working_tree_row_is_announced_when_it_comes_back(graph, qtbot, inline_workers):
    """Committing removes the row and the right pane moves to HEAD; when a
    file is edited again the row returns, and clicking it must show it."""
    graph._queries.is_dirty.execute.return_value = True
    graph.reload()
    _select_row(graph, 0)
    graph._queries.is_dirty.execute.return_value = False
    graph.reload()  # committed: the row is gone
    graph._queries.is_dirty.execute.return_value = True
    graph.reload()  # edited again: the row is back

    with qtbot.waitSignal(graph.commit_selected, timeout=1000) as shown:
        _select_row(graph, 0)

    assert shown.args == [WORKING_TREE_OID]


# ── Ref badges ───────────────────────────────────────────────────────────────


def _badges(graph: GraphWidget, row: int) -> list[str]:
    return graph._model.data(graph._model.index(row, 0), INFO_ROLE).branch_names


def test_scrolling_to_the_next_page_keeps_the_detached_head_badge(graph, inline_workers):
    """`git checkout v1.0`: the commit shows HEAD and the tag. Loading the
    next page used to relabel it with the tag alone."""
    tag = Tag(
        name="v1.0", target_oid="c0", is_annotated=False, message=None, tagger=None, timestamp=None
    )
    graph._queries.get_tags.execute.return_value = [tag]
    graph.reload()
    assert _badges(graph, 0) == ["HEAD", "tag:v1.0"]

    graph._load_more()

    assert _badges(graph, 0) == ["HEAD", "tag:v1.0"]


# ── The working-tree row ─────────────────────────────────────────────────────


def test_a_merge_with_conflicts_draws_no_lane_to_a_merge_head_not_loaded(graph, inline_workers):
    """The walk does not push MERGE_HEAD, so its commit is usually not among
    the rows. A parent that never arrives held its lane open past every
    commit, down to the bottom of history."""
    graph._queries.is_dirty.execute.return_value = True
    graph._queries.get_repo_state.execute.return_value = RepoStateInfo(
        state=RepoState.MERGING, head_branch="main"
    )
    graph._queries.get_merge_head.execute.return_value = "feature-tip"

    graph.reload()

    lanes = [graph._model.data(graph._model.index(row, 0), LANE_ROLE) for row in range(1, 10)]
    assert all(lane.lines == [] for lane in lanes)


# ── Clicking a branch while showing a file's history ─────────────────────────


def test_a_branch_outside_the_file_history_is_shown_in_the_full_graph(graph, inline_workers):
    """File history walks HEAD for commits touching the file, so a branch tip
    that did not touch it can never appear there: the click looked dead."""
    _with_side_branch(graph)
    graph._queries.get_file_history.execute.return_value = _chain(10)[3:5]
    graph.set_path_filter("README.md")

    graph.reload_with_extra_tip("side")

    assert graph._path_filter is None
    assert _current_oid(graph) == "side"


def test_a_branch_whose_tip_is_in_the_file_history_is_selected_there(graph, inline_workers):
    graph._queries.get_file_history.execute.return_value = _chain(10)[3:5]
    graph.set_path_filter("README.md")

    graph.reload_with_extra_tip("c3", ["origin-c3-ahead"])

    assert graph._path_filter == "README.md"
    assert _current_oid(graph) == "c3"


# ── A repo whose history cannot be loaded ────────────────────────────────────


def _unloadable_repo() -> MagicMock:
    """Opens fine, then fails to list its tags: an annotated tag on a tree or
    a blob, as git.git and linux both have, cannot be peeled to a commit."""
    queries = _queries(_chain(3, prefix="b"))
    queries.get_tags.execute.side_effect = RuntimeError("cannot be peeled into a commit")
    return queries


def test_switching_to_a_repo_that_fails_to_load_clears_the_previous_repos_commits(
    graph, inline_workers
):
    graph.reload()
    assert graph._model.rowCount() > 0

    graph.set_buses(_unloadable_repo(), MagicMock())

    assert graph._model.rowCount() == 0


def test_a_failed_load_is_announced_with_its_reason(graph, qtbot, inline_workers):
    with qtbot.waitSignal(graph.load_failed, timeout=1000) as failed:
        graph.set_buses(_unloadable_repo(), MagicMock())

    assert failed.args == ["cannot be peeled into a commit"]


# ── Closing the last repo ────────────────────────────────────────────────────


@pytest.mark.parametrize("n", [30, 3 * PAGE_SIZE], ids=["all-loaded", "more-pages"])
def test_closing_a_repo_scrolled_to_its_end_asks_for_no_more_commits(qtbot, inline_workers, n):
    """The emptied list scrolls back to the top, which reads as reaching
    the bottom. It asked the closed repo for its next page, and the log
    reported a failed load under the empty state."""
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = False
    queries = _queries(_chain(n))
    graph = GraphWidget(queries, MagicMock(), repo_store=repo_store)
    qtbot.addWidget(graph)
    graph.resize(400, 300)
    graph.show()
    graph.reload()
    scrollbar = graph._view.verticalScrollBar()
    qtbot.waitUntil(lambda: scrollbar.maximum() > 0)
    scrollbar.setValue(scrollbar.maximum())
    loads = queries.get_commit_graph.execute.call_count
    failures: list[str] = []
    graph.load_failed.connect(failures.append)

    graph.set_buses(None, None)
    qtbot.waitUntil(lambda: scrollbar.maximum() == 0)
    qtbot.wait(50)

    assert failures == []
    assert queries.get_commit_graph.execute.call_count == loads


def test_searching_with_no_repo_open_reports_no_failed_load(graph, qtbot, inline_workers):
    graph.set_buses(None, None)
    failures: list[str] = []
    graph.load_failed.connect(failures.append)

    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")

    assert failures == []


# ── A search left open when the listing changes ──────────────────────────────


def _match_count(graph: GraphWidget) -> str:
    return graph._search_bar._label.text()


def test_a_search_typed_with_no_repo_open_searches_all_of_the_repo_opened_next(
    graph, inline_workers
):
    """Ctrl+F works on the empty state. The search waited for a full load that
    never ran, so opening a repo searched its first page only: 1 match of 11."""
    graph.set_buses(None, None)
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")

    graph.set_buses(_queries(_chain(4 * PAGE_SIZE)), MagicMock())

    assert graph._model.rowCount() == 4 * PAGE_SIZE
    assert _match_count(graph) == "1 / 11"  # c12 and c120…c129


def test_switching_repos_while_a_search_loads_searches_all_of_the_new_repo(graph, held_workers):
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")

    graph.set_buses(_queries(_chain(4 * PAGE_SIZE, prefix="d")), MagicMock())
    _finish_all(held_workers)

    assert graph._model.rowCount() == 4 * PAGE_SIZE
    assert _match_count(graph) == "1 / 11"
    assert _current_oid(graph) == "d12"


def test_filtering_to_a_file_while_a_search_loads_searches_its_whole_history(graph, held_workers):
    _paged_file_history(graph, 3 * PAGE_SIZE)
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")

    graph.set_path_filter("README.md")
    _finish_all(held_workers)

    assert graph._model.rowCount() == 3 * PAGE_SIZE
    assert _match_count(graph) == "1 / 11"


# ── Clicking a commit further down a file's history ──────────────────────────


def _paged_file_history(graph: GraphWidget, n: int, step: int = 1) -> None:
    """README.md's history: `n` commits, every `step`th of the chain, paged
    like the real walk. Each of them, and no other commit, changed the file.
    HEAD reaches every commit unless the test says otherwise, and none is a
    merge: the two checks that decide whether a commit can be in the history."""
    history = _chain(n * step)[::step]
    graph._queries.is_ancestor.execute.return_value = True
    graph._queries.get_commit_detail.execute.side_effect = lambda oid: Commit(
        oid=oid, message="", author="A", timestamp=datetime(2026, 1, 1), parents=["parent"]
    )
    graph._queries.get_file_history.execute.side_effect = lambda path, limit, skip=0, **_: history[
        skip : skip + limit
    ]
    changed = {c.oid for c in history}
    readme = FileStatus("README.md", StagingState.STAGED, FileDelta.MODIFIED)
    graph._queries.get_commit_files.execute.side_effect = lambda oid: (
        [readme] if oid in changed else []
    )


def test_a_commit_further_down_the_file_history_is_selected_there(graph, inline_workers):
    """A blame line last changed by an old commit: it is in the file's
    history, only not on the first page. Leaving the file history for it
    threw away the view the user had asked for."""
    _paged_file_history(graph, 120)
    graph.set_path_filter("README.md")

    graph.reload_with_extra_tip("c80")

    assert graph._path_filter == "README.md"
    assert _current_oid(graph) == "c80"


def test_a_commit_clicked_before_the_file_history_loads_is_selected_there(graph, held_workers):
    _paged_file_history(graph, 120)
    graph.set_path_filter("README.md")

    graph.reload_with_extra_tip("c80")
    _finish_all(held_workers)

    assert graph._path_filter == "README.md"
    assert _current_oid(graph) == "c80"


def test_a_commit_whose_ancestry_cannot_be_read_is_looked_for_through_the_whole_file_history(
    graph, inline_workers
):
    """When it cannot be told whether HEAD reaches the branch, the file
    history is paged through, and the branch shown once it runs out."""
    _with_side_branch(graph)
    graph._queries.is_ancestor.execute.side_effect = RuntimeError("object not found")
    _paged_file_history(graph, 120)
    graph.set_path_filter("README.md")
    walks = graph._queries.get_file_history.execute
    walks.reset_mock()

    graph.reload_with_extra_tip("side")

    assert walks.call_args.kwargs["limit"] >= 120  # the walk reached the end of the history
    assert graph._path_filter is None
    assert _current_oid(graph) == "side"


def test_a_branch_head_does_not_reach_leaves_a_long_file_history_without_walking_it(
    graph, inline_workers
):
    """File history lists only commits HEAD reaches, so a branch forked off
    it is never there. The click walked the file's whole history first,
    six times over at doubling sizes, the list jumping to its top each time."""
    _with_side_branch(graph)
    graph._queries.is_ancestor.execute.side_effect = lambda ancestor, _head: ancestor != "side"
    _paged_file_history(graph, 1500)
    graph.set_path_filter("README.md")
    walks = graph._queries.get_file_history.execute
    walks.reset_mock()

    graph.reload_with_extra_tip("side")

    assert graph._path_filter is None
    assert _current_oid(graph) == "side"
    walks.assert_not_called()


def test_a_tag_on_a_commit_that_left_the_file_alone_leaves_without_walking_it(
    graph, inline_workers
):
    """A release tag, or master under a feature branch: HEAD reaches it, but
    its commit did not change the file, so it is not in the file's history."""
    graph._queries.is_ancestor.execute.return_value = True
    _paged_file_history(graph, 1500, step=2)  # c0, c2, c4… changed README.md
    graph.set_path_filter("README.md")
    walks = graph._queries.get_file_history.execute
    walks.reset_mock()

    graph.reload_with_extra_tip("c5")

    assert graph._path_filter is None
    assert _current_oid(graph) == "c5"
    walks.assert_not_called()


def test_head_clicked_before_the_file_history_loads_is_selected_there(graph, held_workers):
    """HEAD is not its own ancestor, but it is where the file history starts."""
    _paged_file_history(graph, 120)
    graph._queries.is_ancestor.execute.return_value = False
    graph.set_path_filter("README.md")

    graph.reload_with_extra_tip("c0")
    _finish_all(held_workers)

    assert graph._path_filter == "README.md"
    assert _current_oid(graph) == "c0"


# ── A search left open while a click leaves the file history ─────────────────


def _searching_a_file_history_beside_a_side_branch(graph: GraphWidget) -> None:
    """README.md's history is every 2nd commit of 200, so 'commit 12' matches
    6 commits there and 11 in the full graph. `side` is not in the history."""
    _with_side_branch(graph, length=200)
    _paged_file_history(graph, 100, step=2)
    graph._queries.is_ancestor.execute.side_effect = lambda ancestor, _head: ancestor != "side"
    graph.set_path_filter("README.md")
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")


def test_a_branch_clicked_out_of_a_file_history_still_loading_its_search_searches_the_full_graph(
    graph, held_workers
):
    """Leaving the file history dropped the search waiting on its full load,
    so the full graph showed no count and Enter did nothing."""
    _searching_a_file_history_beside_a_side_branch(graph)

    graph.reload_with_extra_tip("side")
    _finish_all(held_workers)

    assert graph._path_filter is None
    assert _match_count(graph) == "0 / 11"  # c12 and c120…c129; the clicked branch is none
    assert _current_oid(graph) == "side"
    graph._on_search_navigate(1)
    assert _current_oid(graph) == "c12"


def test_a_branch_clicked_out_of_a_searched_file_history_searches_the_full_graph(
    graph, inline_workers
):
    """The file history's '1 / 6' stayed over the full graph, most of its
    matches out of reach and the other five full-graph matches never found.
    Searching again must not move off the branch the click selected."""
    _searching_a_file_history_beside_a_side_branch(graph)
    assert _match_count(graph) == "1 / 6"

    graph.reload_with_extra_tip("side")

    assert graph._model.rowCount() == 201
    assert _match_count(graph) == "0 / 11"
    assert _current_oid(graph) == "side"
    graph._on_search_navigate(-1)
    assert _current_oid(graph) == "c129"
    assert _match_count(graph) == "11 / 11"


# ── Closing a search over the whole history ──────────────────────────────────


def test_a_match_selected_far_down_stays_selected_after_the_search_closes(graph, inline_workers):
    graph.reload()
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")
    graph._on_search_navigate(1)  # c12, then c120
    graph._close_search()

    graph.reload()  # the focus-return auto-reload

    assert _current_oid(graph) == "c120"


def _top_oid(graph: GraphWidget) -> str | None:
    return graph._model.data(graph._view.indexAt(graph._view.viewport().rect().topLeft()), OID_ROLE)


def test_rows_scrolled_to_after_the_search_closes_survive_a_reload(graph, inline_workers):
    graph.resize(400, 300)
    graph.show()
    graph.reload()
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 12")
    graph._close_search()
    scrollbar = graph._view.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
    top = _top_oid(graph)

    graph.reload()

    assert _top_oid(graph) == top


# ── A pick made while an earlier click is still loading ──────────────────────
#
# A click on a branch whose tip is not drawn lands on it once its load
# finishes. The user can pick something else meanwhile, and the last pick has
# to win: the load used to finish by selecting the first click's commit over
# it, and the diff pane followed.


def _first_page_drawn(graph: GraphWidget, held: _HeldWorkers, length: int = 10) -> None:
    """The first page is drawn; `side`, a branch off it, is not on it."""
    _with_side_branch(graph, length)
    graph.reload()
    _finish_all(held)


def _announcements(graph: GraphWidget) -> list[str]:
    """The commits `commit_selected` announces from now on: what the diff pane shows."""
    announced: list[str] = []
    graph.commit_selected.connect(announced.append)
    return announced


def _click_row(graph: GraphWidget, row: int) -> None:
    view = graph._view
    centre = view.visualRect(graph._model.index(row, 0)).center()
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, centre)


@pytest.mark.parametrize(
    "current_again", [False, True], ids=["another-commit", "the-current-commit"]
)
def test_a_drawn_commit_picked_while_a_branch_loads_is_not_replaced_by_the_branch(
    graph, held_workers, current_again
):
    _first_page_drawn(graph, held_workers)
    announced = _announcements(graph)
    if current_again:
        _select_row(graph, 3)  # picked again below, which changes no row
    graph.reload_with_extra_tip("side")  # its tip is not drawn: the load is in flight

    graph.reload_with_extra_tip("c3")
    _finish_all(held_workers)

    assert _current_oid(graph) == "c3"
    assert announced[-1:] == ["c3"]
    assert graph._pending_scroll_oid is None


def test_a_row_clicked_while_a_branch_loads_is_not_replaced_by_the_branch(
    qtbot, graph, held_workers
):
    graph.resize(400, 600)
    graph.show()
    qtbot.waitExposed(graph)
    _first_page_drawn(graph, held_workers)
    announced = _announcements(graph)
    graph.reload_with_extra_tip("side")

    _click_row(graph, 2)
    _finish_all(held_workers)

    assert _current_oid(graph) == "c2"
    assert announced[-1:] == ["c2"]
    assert graph._pending_scroll_oid is None


def test_the_current_row_clicked_while_a_branch_loads_is_not_replaced_by_the_branch(
    qtbot, graph, held_workers
):
    """Clicking the current row changes no row, so no row change reports the pick."""
    graph.resize(400, 600)
    graph.show()
    qtbot.waitExposed(graph)
    _first_page_drawn(graph, held_workers)
    announced = _announcements(graph)
    _select_row(graph, 3)
    graph.reload_with_extra_tip("side")

    _click_row(graph, 3)
    _finish_all(held_workers)

    assert _current_oid(graph) == "c3"
    assert announced[-1:] == ["c3"]
    assert graph._pending_scroll_oid is None


def test_an_arrow_key_pressed_while_a_branch_loads_is_not_replaced_by_the_branch(
    graph, held_workers
):
    _first_page_drawn(graph, held_workers)
    _select_row(graph, 2)
    announced = _announcements(graph)
    graph.reload_with_extra_tip("side")

    QTest.keyClick(graph._view, Qt.Key_Down)
    _finish_all(held_workers)

    assert _current_oid(graph) == "c3"
    assert announced[-1:] == ["c3"]
    assert graph._pending_scroll_oid is None


def test_enter_on_the_current_search_match_while_a_branch_loads_is_not_replaced_by_the_branch(
    graph, held_workers
):
    """Enter goes to a match that is already the current row, which changes no
    row, so no row change reports the pick."""
    _first_page_drawn(graph, held_workers)
    announced = _announcements(graph)
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 3")  # its only match, c3, becomes current
    graph.reload_with_extra_tip("side")

    QTest.keyClick(graph._search_bar.input_widget, Qt.Key_Return)
    _finish_all(held_workers)

    assert _current_oid(graph) == "c3"
    assert announced[-1:] == ["c3"]
    assert graph._pending_scroll_oid is None


def test_a_search_retyped_to_the_current_match_while_a_branch_loads_is_not_replaced_by_the_branch(
    graph, held_workers
):
    """The search jumps to its first match as it is typed, with no Enter."""
    _first_page_drawn(graph, held_workers)
    announced = _announcements(graph)
    graph.open_search()
    search = graph._search_bar.input_widget
    search.setText("commit 3")  # its only match, c3, becomes current
    graph.reload_with_extra_tip("side")

    search.clear()
    search.setText("commit 3")  # the same first match: the current row again
    _finish_all(held_workers)

    assert _current_oid(graph) == "c3"
    assert announced[-1:] == ["c3"]
    assert graph._pending_scroll_oid is None


def test_head_shown_after_a_checkout_while_a_branch_loads_is_not_replaced_by_the_branch(
    graph, held_workers
):
    """A checkout shows the commit HEAD is now on, which can be the row that
    is already current."""
    _first_page_drawn(graph, held_workers)
    announced = _announcements(graph)
    _select_row(graph, 3)
    graph.reload_with_extra_tip("side")

    graph.scroll_to_oid("c3", select=True)  # HEAD, as the window shows it after a checkout
    _finish_all(held_workers)

    assert _current_oid(graph) == "c3"
    assert announced[-1:] == ["c3"]
    assert graph._pending_scroll_oid is None


@pytest.mark.parametrize(
    "selected_before", [True, False], ids=["a-commit-selected", "nothing-selected"]
)
def test_a_stash_picked_while_a_branch_loads_is_not_replaced_by_the_branch(
    graph, held_workers, selected_before
):
    """Clicking a stash clears the graph's selection, then shows the stash in
    the diff pane. With nothing selected, clearing changes no row and Qt
    announces nothing."""
    _first_page_drawn(graph, held_workers)
    if selected_before:
        _select_row(graph, 3)
    graph.reload_with_extra_tip("side")
    announced = _announcements(graph)

    graph.clear_selection()
    _finish_all(held_workers)

    assert _current_oid(graph) is None
    assert announced == []
    assert graph._pending_scroll_oid is None


def test_a_commit_picked_far_down_while_a_branch_loads_is_still_on_screen_when_it_lands(
    qtbot, graph, held_workers
):
    """The load puts back the viewport saved when it began, from before the
    pick, which scrolled the picked row out of sight."""
    graph.resize(400, 300)
    graph.show()
    qtbot.waitExposed(graph)
    _first_page_drawn(graph, held_workers, length=200)
    scrollbar = graph._view.verticalScrollBar()
    qtbot.waitUntil(lambda: scrollbar.maximum() > 0)
    graph.reload_with_extra_tip("side")

    graph.reload_with_extra_tip("c40")
    _finish_all(held_workers)

    assert _current_oid(graph) == "c40"
    picked = graph._view.visualRect(graph._view.currentIndex())
    assert graph._view.viewport().rect().intersects(picked)


def test_a_row_clicked_after_scrolling_while_a_branch_loads_is_still_on_screen_when_it_lands(
    qtbot, graph, held_workers
):
    """The viewport the load saved when it began is not where the user has
    scrolled to since."""
    graph.resize(400, 300)
    graph.show()
    qtbot.waitExposed(graph)
    _first_page_drawn(graph, held_workers, length=200)
    view = graph._view
    scrollbar = view.verticalScrollBar()
    qtbot.waitUntil(lambda: scrollbar.maximum() > 30)
    graph.reload_with_extra_tip("side")
    scrollbar.setValue(30)  # the user scrolls on while it loads

    _click_row(graph, 30)
    _finish_all(held_workers)

    assert _current_oid(graph) == "c30"
    assert view.viewport().rect().intersects(view.visualRect(view.currentIndex()))


def test_enter_on_a_search_match_far_down_while_a_branch_loads_is_still_on_screen_when_it_lands(
    qtbot, graph, held_workers
):
    """The viewport the load saved when it began is not where Enter has taken
    the list back to the match."""
    graph.resize(400, 300)
    graph.show()
    qtbot.waitExposed(graph)
    _first_page_drawn(graph, held_workers, length=200)
    graph.open_search()
    graph._search_bar.input_widget.setText("commit 120")  # loads all 200, then jumps to c120
    _finish_all(held_workers)
    view = graph._view
    qtbot.waitUntil(lambda: view.verticalScrollBar().maximum() > 0)
    view.verticalScrollBar().setValue(0)  # the user scrolls away from the match
    graph.reload_with_extra_tip("side")

    QTest.keyClick(graph._search_bar.input_widget, Qt.Key_Return)
    _finish_all(held_workers)

    assert _current_oid(graph) == "c120"
    assert view.viewport().rect().intersects(view.visualRect(view.currentIndex()))


def test_the_branch_clicked_again_while_it_loads_toward_its_merge_base_still_lands_on_it(
    graph, held_workers
):
    """A branch forked far back loads in rounds, each reaching further for the
    merge base, and lands once it has. Clicking it again picks the commit the
    click is already bound for: stopping the rounds there left its lane
    without the commits it joins."""
    _first_page_drawn(graph, held_workers, length=200)
    graph._queries.get_merge_base.execute.return_value = "c120"
    graph.reload_with_extra_tip("side")
    held_workers.finish_next()  # the first round draws `side`, not yet c120

    graph.reload_with_extra_tip("side")
    _finish_all(held_workers)

    assert graph._row_of("c120") is not None
    assert _current_oid(graph) == "side"


@pytest.mark.parametrize(
    "current_again", [False, True], ids=["another-commit", "the-current-commit"]
)
def test_a_commit_picked_in_the_file_history_while_a_deeper_one_loads_is_not_replaced_by_it(
    graph, held_workers, current_again
):
    _paged_file_history(graph, 120)
    graph.set_path_filter("README.md")
    _finish_all(held_workers)
    announced = _announcements(graph)
    if current_again:
        _select_row(graph, 3)  # picked again below, which changes no row
    graph.reload_with_extra_tip("c80")  # on a later page: the history loads further in

    graph.reload_with_extra_tip("c3")
    _finish_all(held_workers)

    assert graph._path_filter == "README.md"
    assert _current_oid(graph) == "c3"
    assert announced[-1:] == ["c3"]
    assert graph._pending_scroll_oid is None
