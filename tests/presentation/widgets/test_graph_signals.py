"""Signal and method-contract tests for GraphWidget.

Closes coverage gaps not addressed by test_graph_context_menu.py,
test_graph_synthetic.py, or test_keyboard_shortcuts.py: row-selection
emission, scroll_to_oid behavior, reload_with_extra_tip short-circuit,
set_buses bus-detach, and search-with-pending-load dispatch."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QWidget

from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import GraphModel
from git_gui.presentation.widgets.graph import GraphWidget


def _make_commit(oid: str, msg: str = "m") -> Commit:
    return Commit(
        oid=oid,
        message=msg,
        author="A <a@a.com>",
        timestamp=datetime(2026, 1, 1),
        parents=[],
    )


def _make_widget(qtbot, commits: list[Commit] | None = None) -> GraphWidget:
    """Create a minimal GraphWidget bypassing its heavy __init__.

    Same pattern as tests/presentation/widgets/test_graph_synthetic.py.
    """
    w = GraphWidget.__new__(GraphWidget)
    QWidget.__init__(w)

    w._queries = MagicMock()
    w._model = GraphModel(commits or [], {})
    w._loading = False
    w._loaded_count = len(commits or [])
    w._has_more = False
    w._reload_limit = 50
    w._pending_scroll_oid = None
    w._pending_merge_base = None
    w._pending_search = None
    w._extra_tips = None
    w._selected_oid = None
    w._scroll_anchor_oid = None
    w._first_parent = False
    w._stash_btn = MagicMock()

    # _view is used by scroll_to_oid, clear_selection, and _on_row_changed.
    # A MagicMock suffices — we assert on call targets, not Qt rendering.
    w._view = MagicMock()

    # _search_bar is used by search handlers; mock it.
    w._search_bar = MagicMock()
    w._search_matches = []
    w._search_idx = -1

    qtbot.addWidget(w)
    return w


# ── 1. Row selection emits commit_selected ───────────────────────────────


def test_on_row_changed_emits_commit_selected_with_oid(qtbot):
    w = _make_widget(qtbot, commits=[_make_commit("first"), _make_commit("second")])

    # Build a QModelIndex pointing at row 1 (the "second" commit).
    current = w._model.index(1, 0)
    previous = QModelIndex()

    with qtbot.waitSignal(w.commit_selected, timeout=1000) as blocker:
        w._on_row_changed(current, previous)
    assert blocker.args == ["second"]


def test_on_row_changed_skips_reemit_for_already_selected_oid(qtbot):
    """Restoring the selection after an auto-reload's model reset fires
    currentRowChanged with the same oid. Re-emitting there would reload the
    diff/commit-detail pane and reset its scroll, yanking the user away from
    what they were reading — so an unchanged oid must NOT re-emit."""
    w = _make_widget(qtbot, commits=[_make_commit("first"), _make_commit("second")])
    w._selected_oid = "second"  # already viewing this commit

    current = w._model.index(1, 0)  # the "second" commit's row
    previous = QModelIndex()

    with qtbot.assertNotEmitted(w.commit_selected):
        w._on_row_changed(current, previous)


# ── 2. scroll_to_oid updates current row when select=True ────────────────


def test_scroll_to_oid_with_select_sets_current_index(qtbot):
    w = _make_widget(
        qtbot,
        commits=[
            _make_commit("A"),
            _make_commit("B"),
            _make_commit("C"),
        ],
    )

    w.scroll_to_oid("B", select=True)

    # _view.setCurrentIndex should have been called once with an index
    # pointing at row 1 (the row holding B).
    assert w._view.setCurrentIndex.call_count == 1
    called_index = w._view.setCurrentIndex.call_args.args[0]
    assert called_index.row() == 1

    # _view.scrollTo should also have been called.
    assert w._view.scrollTo.call_count == 1


# ── 3. reload_with_extra_tip short-circuits when oid already in model ───


def test_reload_with_extra_tip_short_circuits_when_oid_present(qtbot):
    """When the clicked branch's tip is already in the model, scroll-and-
    select it directly via scroll_to_oid(select=True) — no reload needed."""
    w = _make_widget(
        qtbot,
        commits=[
            _make_commit("HEAD"),
            _make_commit("BRANCH"),
        ],
    )
    w.reload = MagicMock()

    w.reload_with_extra_tip("BRANCH")

    w.reload.assert_not_called()
    # scroll_to_oid(select=True) calls both scrollTo and view.setCurrentIndex
    # on BRANCH's row.
    assert w._view.scrollTo.call_count == 1
    assert w._view.setCurrentIndex.call_count == 1
    selected_index = w._view.setCurrentIndex.call_args.args[0]
    assert selected_index.row() == 1  # BRANCH's row


# ── 4. set_buses(None, None) clears model ────────────────────────────────


def test_set_buses_none_clears_model(qtbot):
    w = _make_widget(qtbot, commits=[_make_commit("A"), _make_commit("B")])
    assert w._model.rowCount() == 2

    w.set_buses(None, None)

    assert w._model.rowCount() == 0


# ── 5. Search with _has_more triggers full reload ────────────────────────


def test_search_with_has_more_triggers_full_reload_and_stores_query(qtbot):
    w = _make_widget(qtbot)
    w._has_more = True
    w.reload = MagicMock()

    w._on_search_text_changed("needle")

    # reload must be called with limit >= 999_999 (the "load everything" signal).
    w.reload.assert_called_once()
    call_kwargs = w.reload.call_args.kwargs
    assert call_kwargs.get("limit", 0) >= 999_999

    # Pending search should be stored for the post-reload dispatch.
    assert w._pending_search == "needle"


# ── 5. reload_with_extra_tip computes merge base for diverged tips ───────


def test_reload_with_extra_tip_computes_merge_base_for_diverged_tip(qtbot):
    """When the clicked oid is not in the model, look up the merge base
    with HEAD and stash it in _pending_merge_base before triggering reload."""
    w = _make_widget(qtbot, commits=[_make_commit("HEAD")])
    w._pending_merge_base = None

    # Stub queries.
    w._queries.get_head_oid.execute.return_value = "HEAD"
    w._queries.get_merge_base.execute.return_value = "BASE"

    # Spy on reload so we don't need a real worker thread.
    w.reload = MagicMock()

    w.reload_with_extra_tip("DIV")  # not in the model

    w._queries.get_merge_base.execute.assert_called_once_with("HEAD", "DIV")
    assert w._pending_scroll_oid == "DIV"
    assert w._pending_merge_base == "BASE"
    w.reload.assert_called_once_with(extra_tips=["DIV"])


# ── 6. _on_reload_done gates on merge base ──────────────────────────────


def _make_commit_with_oid(oid):
    """Helper for the gate tests — minimal Commit with just the oid set."""
    return _make_commit(oid)


def test_on_reload_done_retries_when_merge_base_not_loaded(qtbot):
    """If the target is loaded but the merge base is not, and _has_more is
    True and the limit is below the cap, reload is called again with the
    limit doubled."""
    from git_gui.presentation.models.graph_model import GraphModel

    w = _make_widget(qtbot, commits=[_make_commit("HEAD"), _make_commit("DIV")])
    # Reset model so the on_reload_done loop sees the loaded set after this call.
    w._model = GraphModel(
        [_make_commit("HEAD"), _make_commit("DIV")],
        {},
    )
    w._pending_scroll_oid = "DIV"
    w._pending_merge_base = "BASE"  # NOT in the loaded set
    w._has_more = True
    # _reload_limit must equal len(commits) so _has_more stays True after the
    # _on_reload_done recomputation (len(commits) == self._reload_limit).
    w._reload_limit = 2
    w._extra_tips = ["DIV"]
    w.reload = MagicMock()

    w._on_reload_done(
        commits=[_make_commit("HEAD"), _make_commit("DIV")],
        branches=[],
        tags=[],
        is_dirty=False,
        head_oid="HEAD",
        repo_state_info=None,
        merge_head=None,
        first_parent=False,
    )

    # Pending state preserved; reload called again with doubled limit.
    assert w._pending_scroll_oid == "DIV"
    assert w._pending_merge_base == "BASE"
    w.reload.assert_called_once_with(extra_tips=["DIV"], limit=4)


def test_on_reload_done_scrolls_when_target_and_base_both_loaded(qtbot):
    """When both target and merge base are in the loaded set, scroll and
    clear pending state — no further reload."""
    from git_gui.presentation.models.graph_model import GraphModel

    w = _make_widget(
        qtbot,
        commits=[
            _make_commit("HEAD"),
            _make_commit("DIV"),
            _make_commit("BASE"),
        ],
    )
    w._model = GraphModel(
        [
            _make_commit("HEAD"),
            _make_commit("DIV"),
            _make_commit("BASE"),
        ],
        {},
    )
    w._pending_scroll_oid = "DIV"
    w._pending_merge_base = "BASE"
    w._has_more = True
    w._reload_limit = 50
    w._extra_tips = ["DIV"]
    w.reload = MagicMock()

    w._on_reload_done(
        commits=[
            _make_commit("HEAD"),
            _make_commit("DIV"),
            _make_commit("BASE"),
        ],
        branches=[],
        tags=[],
        is_dirty=False,
        head_oid="HEAD",
        repo_state_info=None,
        merge_head=None,
        first_parent=False,
    )

    assert w._pending_scroll_oid is None
    assert w._pending_merge_base is None
    w.reload.assert_not_called()
    # scroll_to_oid(select=True) — scroll AND select the clicked branch's
    # tip so its row is highlighted and its commit loads in the diff pane.
    assert w._view.scrollTo.call_count == 1
    assert w._view.setCurrentIndex.call_count == 1
    selected_index = w._view.setCurrentIndex.call_args.args[0]
    assert selected_index.row() == 1  # DIV's row


def test_on_reload_done_scrolls_to_loaded_target_at_max_reload_limit(qtbot):
    """At MAX_RELOAD_LIMIT with the merge base still unreachable, stop retrying
    but STILL scroll+select the target if it's loaded — don't silently abandon
    the click (the converging lane is best-effort; locating the tip is not)."""
    from git_gui.presentation.models.graph_model import GraphModel
    from git_gui.presentation.widgets.graph import MAX_RELOAD_LIMIT

    w = _make_widget(qtbot, commits=[_make_commit("HEAD"), _make_commit("DIV")])
    w._model = GraphModel(
        [_make_commit("HEAD"), _make_commit("DIV")],
        {},
    )
    w._pending_scroll_oid = "DIV"
    w._pending_merge_base = "BASE"  # merge base never reachable within the cap
    w._has_more = True
    w._reload_limit = MAX_RELOAD_LIMIT  # already at the cap
    w._extra_tips = ["DIV"]
    w.reload = MagicMock()

    w._on_reload_done(
        commits=[_make_commit("HEAD"), _make_commit("DIV")],
        branches=[],
        tags=[],
        is_dirty=False,
        head_oid="HEAD",
        repo_state_info=None,
        merge_head=None,
        first_parent=False,
    )

    assert w._pending_scroll_oid is None
    assert w._pending_merge_base is None
    w.reload.assert_not_called()
    # Target DIV is loaded → scroll AND select it even though BASE never loaded.
    assert w._view.scrollTo.call_count == 1
    assert w._view.setCurrentIndex.call_count == 1
    assert w._view.setCurrentIndex.call_args.args[0].row() == 1  # DIV's row


def test_on_reload_done_gives_up_without_scroll_when_target_not_loaded(qtbot):
    """At the cap with the target itself not loaded, clear pending state and
    do not scroll (nothing to scroll to)."""
    from git_gui.presentation.models.graph_model import GraphModel
    from git_gui.presentation.widgets.graph import MAX_RELOAD_LIMIT

    w = _make_widget(qtbot, commits=[_make_commit("HEAD")])
    w._model = GraphModel([_make_commit("HEAD")], {})
    w._pending_scroll_oid = "DIV"  # not in the loaded set
    w._pending_merge_base = "BASE"
    w._has_more = True
    w._reload_limit = MAX_RELOAD_LIMIT
    w._extra_tips = ["DIV"]
    w.reload = MagicMock()

    w._on_reload_done(
        commits=[_make_commit("HEAD")],
        branches=[],
        tags=[],
        is_dirty=False,
        head_oid="HEAD",
        repo_state_info=None,
        merge_head=None,
        first_parent=False,
    )

    assert w._pending_scroll_oid is None
    assert w._pending_merge_base is None
    w.reload.assert_not_called()
    assert w._view.scrollTo.call_count == 0


# ── 7. extra_tips stickiness across bare reload() ──────────────────────


def test_reload_preserves_extra_tips_when_called_without_args(qtbot):
    """A bare reload() (e.g. from MainWindow._reload via RepoChangeDetector)
    must not wipe self._extra_tips. The user's last-clicked diverged branch
    has to survive auto-reloads."""
    w = _make_widget(qtbot)
    w._extra_tips = ["DIV"]

    # Replace the worker-spawning Thread so we don't actually fire a thread.
    with patch("threading.Thread"):
        w.reload()

    assert w._extra_tips == ["DIV"], "bare reload() must preserve the user-selected extra tips"


def test_reload_with_explicit_extra_tips_replaces_current(qtbot):
    """An explicit extra_tips=[oid] argument replaces the current value."""
    w = _make_widget(qtbot)
    w._extra_tips = ["OLD"]

    with patch("threading.Thread"):
        w.reload(extra_tips=["NEW"])

    assert w._extra_tips == ["NEW"]


def test_reload_with_empty_list_replaces_with_empty(qtbot):
    """An explicit extra_tips=[] argument clears the value (different from
    None which preserves)."""
    w = _make_widget(qtbot)
    w._extra_tips = ["OLD"]

    with patch("threading.Thread"):
        w.reload(extra_tips=[])

    assert w._extra_tips == []


def test_set_buses_resets_extra_tips_and_pending_state(qtbot):
    """set_buses must reset _extra_tips, _pending_scroll_oid, and
    _pending_merge_base — they belong to the previous repo."""
    w = _make_widget(qtbot)
    w._extra_tips = ["DIV"]
    w._pending_scroll_oid = "DIV"
    w._pending_merge_base = "BASE"

    with patch("threading.Thread"):
        w.set_buses(MagicMock(), MagicMock())

    assert w._extra_tips is None
    assert w._pending_scroll_oid is None
    assert w._pending_merge_base is None


def test_reload_preserves_reload_limit_when_called_without_args(qtbot):
    """A bare reload() must preserve self._reload_limit. After the doubling
    retry has grown the limit (e.g. to 200) so the merge base is loaded, an
    auto-reload from MainWindow._reload must NOT regress to PAGE_SIZE — that
    would drop the merge base from the loaded set and revert the diverged
    lane to a floating circle."""
    w = _make_widget(qtbot)
    w._extra_tips = ["DIV"]
    w._reload_limit = 200

    with patch("threading.Thread"):
        w.reload()

    assert w._reload_limit == 200, "bare reload() must not regress _reload_limit to PAGE_SIZE"


def test_reload_with_explicit_limit_replaces_current(qtbot):
    """An explicit limit argument replaces the current value."""
    w = _make_widget(qtbot)
    w._reload_limit = 200

    with patch("threading.Thread"):
        w.reload(limit=999_999)

    assert w._reload_limit == 999_999


def test_reload_with_extra_tip_selects_clicked_branch_tip(qtbot):
    """Clicking a branch in the sidebar should scroll the graph to the
    branch's tip and select it — the diff pane updates to show that
    tip's commit (the branch the user navigated to)."""
    w = _make_widget(
        qtbot,
        commits=[
            _make_commit("HEAD"),
            _make_commit("BRANCH_TIP"),
        ],
    )
    w.reload = MagicMock()

    w.reload_with_extra_tip("BRANCH_TIP")

    # scroll_to_oid(select=True) — scroll AND select on the same row.
    assert w._view.scrollTo.call_count == 1
    scrolled_index = w._view.scrollTo.call_args.args[0]
    assert scrolled_index.row() == 1  # BRANCH_TIP's row
    assert w._view.setCurrentIndex.call_count == 1
    selected_index = w._view.setCurrentIndex.call_args.args[0]
    assert selected_index.row() == 1


def test_on_row_changed_records_selected_oid(qtbot):
    """_on_row_changed must store the selected oid on _selected_oid so it
    can be restored after a subsequent model reset."""
    w = _make_widget(qtbot, commits=[_make_commit("first"), _make_commit("second")])

    current = w._model.index(1, 0)
    previous = QModelIndex()

    with qtbot.waitSignal(w.commit_selected, timeout=1000):
        w._on_row_changed(current, previous)

    assert w._selected_oid == "second"


def test_on_reload_done_restores_selection_without_scrolling(qtbot):
    """After a model reset clears the current row, _on_reload_done should
    re-select the row matching _selected_oid via the selection model with
    full-row flags. The selection model path doesn't auto-scroll, so the
    gate's scroll position is preserved."""
    from PySide6.QtCore import QItemSelectionModel

    from git_gui.presentation.models.graph_model import GraphModel

    w = _make_widget(qtbot)
    w._selected_oid = "HEAD"
    w._model = GraphModel([_make_commit("HEAD"), _make_commit("OTHER")], {})

    w._on_reload_done(
        commits=[_make_commit("HEAD"), _make_commit("OTHER")],
        branches=[],
        tags=[],
        is_dirty=False,
        head_oid="HEAD",
        repo_state_info=None,
        merge_head=None,
        first_parent=False,
    )

    sm_set_current = w._view.selectionModel().setCurrentIndex
    assert sm_set_current.call_count == 1
    called_index = sm_set_current.call_args.args[0]
    assert called_index.row() == 0
    flags = sm_set_current.call_args.args[1]
    assert flags & QItemSelectionModel.Rows
    assert flags & QItemSelectionModel.ClearAndSelect


def test_on_reload_done_skips_restore_when_selected_oid_is_none(qtbot):
    """If no commit was previously selected, no restore happens."""
    from git_gui.presentation.models.graph_model import GraphModel

    w = _make_widget(qtbot)
    w._selected_oid = None
    w._model = GraphModel([_make_commit("HEAD")], {})

    w._on_reload_done(
        commits=[_make_commit("HEAD")],
        branches=[],
        tags=[],
        is_dirty=False,
        head_oid="HEAD",
        repo_state_info=None,
        merge_head=None,
        first_parent=False,
    )

    assert w._view.selectionModel().setCurrentIndex.call_count == 0


def test_on_reload_done_skips_restore_during_retry(qtbot):
    """When the gate triggers a retry, the model is about to be reset again
    by the next reload — skip the restore to avoid wasted work."""
    from git_gui.presentation.models.graph_model import GraphModel

    w = _make_widget(qtbot)
    w._selected_oid = "HEAD"
    w._model = GraphModel([_make_commit("HEAD"), _make_commit("DIV")], {})
    w._pending_scroll_oid = "DIV"
    w._pending_merge_base = "BASE"  # not in the loaded set
    w._has_more = True
    w._reload_limit = 2
    w._extra_tips = ["DIV"]
    w.reload = MagicMock()  # spy on the retry call

    w._on_reload_done(
        commits=[_make_commit("HEAD"), _make_commit("DIV")],
        branches=[],
        tags=[],
        is_dirty=False,
        head_oid="HEAD",
        repo_state_info=None,
        merge_head=None,
        first_parent=False,
    )

    # Retry was triggered — restore should not have run.
    w.reload.assert_called_once()
    assert w._view.selectionModel().setCurrentIndex.call_count == 0


def test_set_buses_resets_selected_oid(qtbot):
    """A repo switch must also clear _selected_oid — the previous repo's
    selection is meaningless in the new repo."""
    w = _make_widget(qtbot)
    w._selected_oid = "HEAD"

    with patch("threading.Thread"):
        w.set_buses(MagicMock(), MagicMock())

    assert w._selected_oid is None


def test_set_buses_resets_reload_limit_to_page_size(qtbot):
    """set_buses must reset _reload_limit to PAGE_SIZE so the new repo
    starts fresh — otherwise a previously-doubled limit (up to 2000) would
    over-load on the new repo's first render."""
    from git_gui.presentation.widgets.graph import PAGE_SIZE

    w = _make_widget(qtbot)
    w._reload_limit = 1600

    with patch("threading.Thread"):
        w.set_buses(MagicMock(), MagicMock())

    assert w._reload_limit == PAGE_SIZE


def test_on_reload_done_skips_base_check_when_pending_merge_base_is_none(qtbot):
    """When _pending_merge_base is None (HEAD unborn, branch == HEAD, or
    disjoint histories), only the target gate applies — same as today's
    behavior."""
    from git_gui.presentation.models.graph_model import GraphModel

    w = _make_widget(qtbot, commits=[_make_commit("HEAD"), _make_commit("DIV")])
    w._model = GraphModel(
        [_make_commit("HEAD"), _make_commit("DIV")],
        {},
    )
    w._pending_scroll_oid = "DIV"
    w._pending_merge_base = None
    w._has_more = True
    w._reload_limit = 50
    w._extra_tips = ["DIV"]
    w.reload = MagicMock()

    w._on_reload_done(
        commits=[_make_commit("HEAD"), _make_commit("DIV")],
        branches=[],
        tags=[],
        is_dirty=False,
        head_oid="HEAD",
        repo_state_info=None,
        merge_head=None,
        first_parent=False,
    )

    # Target loaded + base check skipped → scroll, no retry.
    assert w._pending_scroll_oid is None
    assert w._pending_merge_base is None
    w.reload.assert_not_called()
