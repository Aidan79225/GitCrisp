# Graph + Sidebar Signal Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ~15 behavior tests that lock in the public signal / method contracts of `SidebarWidget` and `GraphWidget`, closing the highest-risk regression gaps identified in the code-health survey.

**Architecture:** Two new pytest-qt test files — `tests/presentation/widgets/test_sidebar_signals.py` (10 tests) and `tests/presentation/widgets/test_graph_signals.py` (5 tests). Tests use `MagicMock()` buses, populate the widget's model directly for deterministic state, and exercise handlers through their public callable surface (`_on_click`, `_on_double_click`, `_show_context_menu`, `_on_row_changed`, `scroll_to_oid`, `reload_with_extra_tip`, `set_buses`, `_on_search_text_changed`). For context-menu paths, a helper captures the `QMenu` instance via a `QMenu.__init__` spy, then triggers actions by text.

**Tech Stack:** Python 3.13, PySide6 (Qt), pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-21-graph-sidebar-signal-tests-design.md`

---

## File Structure

**New files:**
- `tests/presentation/widgets/test_sidebar_signals.py` — 10 tests
- `tests/presentation/widgets/test_graph_signals.py` — 5 tests

**Not touched:** production code, existing tests, conftest, README.

---

## API reference (confirmed by reading source before plan was written)

Confirming exact names so test code below is concrete — do NOT rediscover during implementation.

### `SidebarWidget` — `git_gui/presentation/widgets/sidebar.py`

- Constructor: `SidebarWidget(queries, commands, remote_tag_cache=None, repo_path=None, parent=None)`.
- Internal attrs: `self._tree` (QTreeView), `self._model` (QStandardItemModel), `self._commands`.
- Role keys (module-level):
  - `Qt.UserRole` → value (branch name, tag name, stash index as string)
  - `Qt.UserRole + 1` → kind string: `"branch"`, `"remote_branch"`, `"stash"`, `"tag"`, `"header"`
  - `_IS_HEAD_ROLE = Qt.UserRole + 2` → bool
  - `_TARGET_OID_ROLE = Qt.UserRole + 3` → target oid string
- Click handlers:
  - `_on_click(index)`: reads kind + `_TARGET_OID_ROLE`; emits `stash_clicked`, `tag_clicked`, or `branch_clicked`.
  - `_on_double_click(index)`: if kind is `"branch"`, calls `self._commands.checkout.execute(value)` then emits `branch_checkout_requested(value)`.
  - `_show_context_menu(pos)`: reads kind + value from index at pos, builds `QMenu`, calls `menu.exec(...)`. Actions are lambdas that emit signals / run commands.
- `set_buses(queries, commands)`: if `queries is None`, calls `self._model.clear()`; else calls `self.reload()`.

### `GraphWidget` — `git_gui/presentation/widgets/graph.py`

- Constructor is heavy — use `GraphWidget.__new__(GraphWidget)` + partial init (pattern from `test_graph_synthetic.py:26-47`).
- Internal attrs: `self._view` (QTableView), `self._model` (`GraphModel`), `self._loading`, `self._has_more`, `self._reload_limit`, `self._pending_scroll_oid`, `self._pending_search`.
- `_on_row_changed(current, previous)` emits `commit_selected` with OID from `self._model.data(self._model.index(current.row(), 0), Qt.UserRole)`.
- `scroll_to_oid(oid, select=False)` walks `_model` looking for matching OID in column 0 `Qt.UserRole`; if found, calls `self._view.scrollTo(index, ...)` and optionally `self._view.setCurrentIndex(index)`.
- `reload_with_extra_tip(oid)` walks the current model; if oid is present, calls `self.scroll_to_oid(oid, select=True)` and returns. Otherwise sets `_pending_scroll_oid = oid` and calls `self.reload(extra_tips=[oid])`.
- `reload(extra_tips=None, limit=PAGE_SIZE)` — returns early if `_loading`. Otherwise sets `_loading=True`, `_extra_tips=extra_tips`, `_reload_limit=limit`, then spawns a worker thread.
- `set_buses(queries, commands)`: if `queries is None`, calls `self._model.reload([], {})`. Else calls `self.reload()`.
- `_on_search_text_changed(text)` — if `_has_more=True`, sets `_pending_search` and calls `self.reload(limit=999_999)`. Otherwise calls `_run_search(needle)`.

### `GraphModel` — minimum you need for tests

From `test_graph_synthetic.py:32`: `GraphModel([], {})` constructs an empty model. `GraphModel(commits_list, refs_dict)` populates it. To populate with one synthetic OID for tests, use e.g. `GraphModel([Commit(oid="abc", message="m", author="a", timestamp=datetime(...), parents=[])], {})`.

---

## Task 1: Sidebar signal tests

Create `tests/presentation/widgets/test_sidebar_signals.py` with a fixture plus 10 tests. Commit the full file in one shot.

**Files:**
- Create: `tests/presentation/widgets/test_sidebar_signals.py`

- [ ] **Step 1: Create the test file**

Write `tests/presentation/widgets/test_sidebar_signals.py`:

```python
"""Signal and method-contract tests for SidebarWidget.

Covers public-API regressions: single-click routing by item kind,
double-click branch checkout, context-menu action emissions, and
bus-detach model clearing. No rendering or async-reload tests here."""
from __future__ import annotations
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import QMenu

from git_gui.presentation.widgets.sidebar import (
    SidebarWidget,
    _IS_HEAD_ROLE,
    _TARGET_OID_ROLE,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _branch_item(name: str, oid: str, *, is_head: bool = False) -> QStandardItem:
    child = QStandardItem(name)
    child.setEditable(False)
    child.setData(name, Qt.UserRole)
    child.setData("branch", Qt.UserRole + 1)
    child.setData(oid, _TARGET_OID_ROLE)
    if is_head:
        child.setData(True, _IS_HEAD_ROLE)
    return child


def _remote_branch_item(name: str, oid: str) -> QStandardItem:
    child = QStandardItem(name)
    child.setEditable(False)
    child.setData(name, Qt.UserRole)
    child.setData("remote_branch", Qt.UserRole + 1)
    child.setData(oid, _TARGET_OID_ROLE)
    return child


def _stash_item(message: str, index: int, oid: str) -> QStandardItem:
    child = QStandardItem(message)
    child.setEditable(False)
    child.setData(str(index), Qt.UserRole)
    child.setData("stash", Qt.UserRole + 1)
    child.setData(oid, _TARGET_OID_ROLE)
    return child


def _tag_item(name: str, oid: str) -> QStandardItem:
    child = QStandardItem(name)
    child.setEditable(False)
    child.setData(name, Qt.UserRole)
    child.setData("tag", Qt.UserRole + 1)
    child.setData(oid, _TARGET_OID_ROLE)
    return child


def _add_section(sidebar: SidebarWidget, title: str, children: list[QStandardItem]) -> QStandardItem:
    header = QStandardItem(title)
    header.setEditable(False)
    header.setData("header", Qt.UserRole + 1)
    for c in children:
        header.appendRow(c)
    sidebar._model.appendRow(header)
    return header


def _capture_menu_actions(sidebar: SidebarWidget, item: QStandardItem) -> dict:
    """Invoke _show_context_menu for the item's index and return a dict of
    {action_text: QAction} by spying on QMenu construction and blocking exec.

    Mocks sidebar._tree.indexAt at the instance level so the handler resolves
    the pos we provide to the item's real QModelIndex."""
    from PySide6.QtCore import QPoint

    captured: list[QMenu] = []
    original_init = QMenu.__init__

    def spy_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        captured.append(self)

    idx = sidebar._model.indexFromItem(item)
    sidebar._tree.indexAt = MagicMock(return_value=idx)

    with patch.object(QMenu, "__init__", spy_init), \
         patch.object(QMenu, "exec", return_value=None):
        sidebar._show_context_menu(QPoint(0, 0))

    assert captured, "No QMenu was constructed"
    menu = captured[-1]
    return {action.text(): action for action in menu.actions() if action.text()}


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


# ── 1. Single-click routing ──────────────────────────────────────────────


def test_single_click_local_branch_emits_branch_clicked_with_oid(sidebar, qtbot):
    w, _, _ = sidebar
    item = _branch_item("feature", "abc123")
    _add_section(w, "LOCAL BRANCHES", [item])
    idx = w._model.indexFromItem(item)

    with qtbot.waitSignal(w.branch_clicked, timeout=1000) as blocker:
        w._on_click(idx)
    assert blocker.args == ["abc123"]


def test_single_click_tag_emits_tag_clicked_with_target_oid(sidebar, qtbot):
    """Tag click must emit the target oid, NOT the tag name."""
    w, _, _ = sidebar
    item = _tag_item("v1.0", "def456")
    _add_section(w, "TAGS", [item])
    idx = w._model.indexFromItem(item)

    with qtbot.waitSignal(w.tag_clicked, timeout=1000) as blocker:
        w._on_click(idx)
    assert blocker.args == ["def456"]


def test_single_click_stash_emits_stash_clicked_with_oid(sidebar, qtbot):
    w, _, _ = sidebar
    item = _stash_item("my stash", index=0, oid="789abc")
    _add_section(w, "STASHES", [item])
    idx = w._model.indexFromItem(item)

    with qtbot.waitSignal(w.stash_clicked, timeout=1000) as blocker:
        w._on_click(idx)
    assert blocker.args == ["789abc"]


# ── 2. Double-click branch ───────────────────────────────────────────────


def test_double_click_branch_executes_checkout_and_emits_signal(sidebar, qtbot):
    w, _, commands = sidebar
    item = _branch_item("feature", "abc123")
    _add_section(w, "LOCAL BRANCHES", [item])
    idx = w._model.indexFromItem(item)

    with qtbot.waitSignal(w.branch_checkout_requested, timeout=1000) as blocker:
        w._on_double_click(idx)

    commands.checkout.execute.assert_called_once_with("feature")
    assert blocker.args == ["feature"]


# ── 3. Context menu: remote-branch fetch parses remote name ──────────────


def test_remote_branch_fetch_menu_emits_remote_name_only(sidebar, qtbot):
    w, _, _ = sidebar
    item = _remote_branch_item("origin/feature", "abc123")
    _add_section(w, "REMOTE BRANCHES", [item])

    actions = _capture_menu_actions(w, item)
    assert "Fetch" in actions

    with qtbot.waitSignal(w.fetch_requested, timeout=1000) as blocker:
        actions["Fetch"].trigger()
    assert blocker.args == ["origin"]


# ── 4. Context menu: stash actions emit correct index ────────────────────


def test_stash_pop_menu_emits_correct_index(sidebar, qtbot):
    w, _, _ = sidebar
    item = _stash_item("third stash", index=2, oid="0xabc")
    _add_section(w, "STASHES", [item])

    actions = _capture_menu_actions(w, item)
    assert "Pop" in actions

    with qtbot.waitSignal(w.stash_pop_requested, timeout=1000) as blocker:
        actions["Pop"].trigger()
    assert blocker.args == [2]


def test_stash_apply_menu_emits_correct_index(sidebar, qtbot):
    w, _, _ = sidebar
    item = _stash_item("third stash", index=2, oid="0xabc")
    _add_section(w, "STASHES", [item])

    actions = _capture_menu_actions(w, item)
    assert "Apply" in actions

    with qtbot.waitSignal(w.stash_apply_requested, timeout=1000) as blocker:
        actions["Apply"].trigger()
    assert blocker.args == [2]


def test_stash_drop_menu_emits_correct_index(sidebar, qtbot):
    w, _, _ = sidebar
    item = _stash_item("third stash", index=2, oid="0xabc")
    _add_section(w, "STASHES", [item])

    actions = _capture_menu_actions(w, item)
    assert "Drop" in actions

    with qtbot.waitSignal(w.stash_drop_requested, timeout=1000) as blocker:
        actions["Drop"].trigger()
    assert blocker.args == [2]


# ── 5. Context menu: tag delete emits tag name ───────────────────────────


def test_tag_delete_menu_emits_tag_name(sidebar, qtbot):
    w, _, _ = sidebar
    item = _tag_item("v2.1", "0xdef")
    _add_section(w, "TAGS", [item])

    actions = _capture_menu_actions(w, item)
    assert "Delete" in actions

    with qtbot.waitSignal(w.tag_delete_requested, timeout=1000) as blocker:
        actions["Delete"].trigger()
    assert blocker.args == ["v2.1"]


# ── 6. Bus detach clears model ───────────────────────────────────────────


def test_set_buses_none_clears_model(sidebar):
    w, _, _ = sidebar
    _add_section(w, "LOCAL BRANCHES", [_branch_item("main", "aaa")])
    assert w._model.rowCount() == 1

    w.set_buses(None, None)
    assert w._model.rowCount() == 0
```

- [ ] **Step 2: Run the new tests**

Run: `uv run pytest tests/presentation/widgets/test_sidebar_signals.py -v`

Expected: **10 passed**.

If any fail with role-key mismatches, re-confirm `_IS_HEAD_ROLE` / `_TARGET_OID_ROLE` / `Qt.UserRole + 1` constants by reading `git_gui/presentation/widgets/sidebar.py:24-25` (they are `Qt.UserRole + 2` and `Qt.UserRole + 3` respectively).

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest tests/ -q`

Expected: **516 passed** (506 existing + 10 new).

- [ ] **Step 4: Commit**

```bash
git add tests/presentation/widgets/test_sidebar_signals.py
git commit -m "test(sidebar): add signal and menu-contract tests"
```

---

## Task 2: Graph signal tests

Create `tests/presentation/widgets/test_graph_signals.py` with 5 tests. Uses the `GraphWidget.__new__` + partial-init pattern from `test_graph_synthetic.py` to avoid the heavy constructor.

**Files:**
- Create: `tests/presentation/widgets/test_graph_signals.py`

- [ ] **Step 1: Create the test file**

Write `tests/presentation/widgets/test_graph_signals.py`:

```python
"""Signal and method-contract tests for GraphWidget.

Closes coverage gaps not addressed by test_graph_context_menu.py,
test_graph_synthetic.py, or test_keyboard_shortcuts.py: row-selection
emission, scroll_to_oid behavior, reload_with_extra_tip short-circuit,
set_buses bus-detach, and search-with-pending-load dispatch."""
from __future__ import annotations
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtWidgets import QWidget

from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import GraphModel
from git_gui.presentation.widgets.graph import GraphWidget


def _make_commit(oid: str, msg: str = "m") -> Commit:
    return Commit(
        oid=oid, message=msg, author="A <a@a.com>",
        timestamp=datetime(2026, 1, 1), parents=[],
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
    w._pending_search = None
    w._stash_btn = MagicMock()
    w._update_column_widths = lambda: None

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


# ── 2. scroll_to_oid updates current row when select=True ────────────────


def test_scroll_to_oid_with_select_sets_current_index(qtbot):
    w = _make_widget(qtbot, commits=[
        _make_commit("A"), _make_commit("B"), _make_commit("C"),
    ])

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
    w = _make_widget(qtbot, commits=[
        _make_commit("X"), _make_commit("Y"),
    ])
    # Ensure reload is NOT called; replace it with a spy.
    w.reload = MagicMock()

    w.reload_with_extra_tip("X")

    w.reload.assert_not_called()
    # scroll_to_oid should have been called — verify via _view.setCurrentIndex.
    assert w._view.setCurrentIndex.call_count == 1


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
```

- [ ] **Step 2: Run the new tests**

Run: `uv run pytest tests/presentation/widgets/test_graph_signals.py -v`

Expected: **5 passed**.

If test 3 fails with "reload was called", confirm the short-circuit path at `git_gui/presentation/widgets/graph.py:331-341` — the current implementation iterates the model looking for a matching row `Qt.UserRole` and returns early via `scroll_to_oid` without calling `self.reload`.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest tests/ -q`

Expected: **521 passed** (516 after Task 1 + 5 new).

- [ ] **Step 4: Commit**

```bash
git add tests/presentation/widgets/test_graph_signals.py
git commit -m "test(graph): add row-selection, scroll, reload, bus-detach, and search tests"
```

---

## Done

After Task 2, sub-project D is complete. Final state:

- `tests/presentation/widgets/test_sidebar_signals.py` (10 tests).
- `tests/presentation/widgets/test_graph_signals.py` (5 tests).
- Full suite: 521 tests passing (506 baseline + 15 new).
- Zero production-code changes. Zero refactor.
