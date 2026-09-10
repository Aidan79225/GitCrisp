# Graph + Sidebar Signal Tests — Design

**Date:** 2026-04-21
**Status:** Proposed

## Goal

Close the highest-risk gaps in widget-test coverage for `GraphWidget` and `SidebarWidget` by adding a tight safety net of ~15 behavior tests against their public signal / method contract. Focus on silent-regression protection — not exhaustive coverage.

## Scope

- Two new test files under `tests/presentation/widgets/`: `test_graph_signals.py` (~5 tests) and `test_sidebar_signals.py` (~10 tests).
- Tests exercise the widgets through their public API (signals and public methods), not through Qt event dispatch.
- No production code changes. No new fixtures module. Each test file holds its own local `_make_widget` helper.

## UX Decisions

| Concern | Decision |
|---|---|
| Test depth | Tight safety net (option A from brainstorming). ~15 tests total. |
| What to cover | Signal emission, method contracts, data-routing correctness (OID vs name, index extraction, remote-name parsing). |
| What not to cover | Column-width math, hover visuals, paint events, sorting, icon rendering, async thread timing, end-to-end MainWindow wiring. |
| Action invocation | Prefer calling handler methods directly (`_on_item_clicked`, `_handle_branch_checkout`) over simulating mouse events. Less fragile, same behavioral coverage. |
| Model setup | Directly populate the tree / graph model in test setup; bypass async reload workers. |
| Bus handling | `MagicMock()` for both `QueryBus` and `CommandBus`. Stub only the methods the widget touches. |

## Approach

Follow the patterns already in use:

- **Full construction** where it's cheap — `SidebarWidget(queries, commands, remote_tag_cache=None, repo_path=None)` constructs fine with mock buses (as `test_diff_widget.py` does for `DiffWidget`).
- **`__new__` + partial init** where full construction is heavy — `GraphWidget.__new__(GraphWidget)` + manually set `_queries`, `_model`, `_table`, etc. (the pattern from `test_graph_synthetic.py`).
- **Direct handler calls** for actions — `widget._on_item_clicked(item)` instead of dispatching a mouse event. Equivalent behavior, more reliable.
- **`qtbot.waitSignal`** for signal assertions with a short timeout (the pattern from `test_main_window_session_factory.py`).

## Architecture & files touched

**New files:**
```
tests/presentation/widgets/
├── test_graph_signals.py
└── test_sidebar_signals.py
```

**Not touched:** production code, existing tests, conftest, CI config, README.

## Test inventory

### `test_graph_signals.py`

1. **`test_row_selected_emits_commit_selected_with_oid`** — populate the model with two rows; call the row-change handler (`_on_row_changed`) with the second row; assert `commit_selected` signal emits that row's OID.

2. **`test_scroll_to_oid_updates_current_row_when_select_true`** — populate the model with OIDs `[A, B, C]`; call `scroll_to_oid("B", select=True)`; assert `widget._table.currentIndex().row()` equals the index of `B`.

3. **`test_reload_with_extra_tip_scrolls_without_reloading_when_oid_present`** — pre-populate the model containing `oid=X`; reset the `queries.get_commit_graph.execute` mock; call `reload_with_extra_tip(X)`; assert `queries.get_commit_graph.execute.call_count == 0` (short-circuit path) and the widget's current row is `X`.

4. **`test_set_buses_none_clears_model`** — populate the model; call `set_buses(None, None)`; assert `widget._model.rowCount() == 0`.

5. **`test_search_with_has_more_triggers_full_reload`** — set `widget._has_more = True`; patch `widget.reload` with a mock; call the search entry point (`_on_search_submitted` or equivalent — confirm name from source); assert `widget.reload` was called with a large `limit` (≥100000) and `pending_search_query` was stored.

### `test_sidebar_signals.py`

1. **`test_single_click_local_branch_emits_branch_clicked_with_oid`** — inject a local-branch item carrying `target_oid="abc123"` in `Qt.UserRole`; call `_on_item_clicked(item)`; assert `branch_clicked` emits `"abc123"`.

2. **`test_single_click_tag_emits_tag_clicked_with_target_oid`** — inject a tag item with `tag_name="v1.0"` and `target_oid="def456"`; click; assert `tag_clicked` emits `"def456"`, NOT the tag name.

3. **`test_single_click_stash_emits_stash_clicked_with_oid`** — inject a stash item with `stash_oid="789abc"`; click; assert `stash_clicked` emits `"789abc"`.

4. **`test_double_click_branch_executes_checkout_and_emits_signal`** — inject a local-branch item named `"feature"`; call the double-click handler; assert `commands.checkout.execute("feature")` was called AND `branch_checkout_requested` emitted `"feature"`.

5. **`test_remote_branch_fetch_menu_emits_remote_name_only`** — inject a remote-branch item named `"origin/feature"`; invoke the fetch context-menu action; assert `fetch_requested` emits `"origin"` (remote name parsed, not full path).

6. **`test_stash_pop_menu_emits_correct_index`** — inject stash items with indexes `[0, 1, 2]`; invoke Pop on the item at index `2`; assert `stash_pop_requested` emits `2`.

7. **`test_stash_apply_menu_emits_correct_index`** — same shape as test 6 but for Apply; assert `stash_apply_requested` emits `2`.

8. **`test_stash_drop_menu_emits_correct_index`** — same shape but for Drop; assert `stash_drop_requested` emits `2`.

9. **`test_tag_delete_menu_emits_tag_name`** — inject a tag item `"v2.1"`; invoke Delete; assert `tag_delete_requested` emits `"v2.1"`.

10. **`test_set_buses_none_clears_model`** — populate the tree; call `set_buses(None, None)`; assert the tree model has zero rows (or root has zero children).

## Fixture pattern

```python
# tests/presentation/widgets/test_sidebar_signals.py
from __future__ import annotations
from unittest.mock import MagicMock
import pytest
from git_gui.presentation.widgets.sidebar import SidebarWidget


@pytest.fixture
def sidebar(qtbot):
    queries = MagicMock()
    queries.get_branches.execute.return_value = []
    queries.get_stashes.execute.return_value = []
    queries.get_tags.execute.return_value = []
    commands = MagicMock()
    w = SidebarWidget(queries, commands, remote_tag_cache=None, repo_path=None)
    qtbot.addWidget(w)
    return w, queries, commands
```

Graph tests use the `__new__` + partial-init pattern from `test_graph_synthetic.py` where full construction would bring in scroll setup, delegate construction, and search-bar wiring that we don't need.

## Item-role contract

Sidebar items store routing data in `Qt.UserRole` (and possibly `Qt.UserRole + 1, +2` per kind). Tests set roles directly via `QStandardItem.setData(value, role)` so the handler sees exactly what the real code would see. The role keys are whatever `sidebar.py` already uses — tests read them via the same constants or attribute names (determined by reading source during implementation).

## Testing discipline

- **Arrange / Act / Assert** blocks explicit in every test.
- **No `time.sleep`.** If something must wait, use `qtbot.waitSignal(...)` with a 2-second timeout.
- **One behavior per test.** Tests don't chain — a single click, a single assertion (or a signal-arg tuple assertion).
- **No assertion on Qt internals** — never check pixel colors, scrollbar values, or render output. Check model state, signal args, and mock call counts.

## Out of scope

- Column-width computation in `GraphWidget`.
- Hover row tracking / `leaveEvent` / `paintEvent`.
- Search-bar UI mechanics beyond the lazy-reload dispatch (already covered by `test_keyboard_shortcuts.py`).
- Reload thread timing, `_LoadSignals` construction, worker lifecycle.
- Sidebar sorting (stashes reverse chronological, tags alphabetical, etc.).
- Remote-tag cloud-icon rendering and remote-tag-cache integration.
- Any changes to production code.
- Reaching test counts beyond ~15 (see options B/C in brainstorming — deferred).
