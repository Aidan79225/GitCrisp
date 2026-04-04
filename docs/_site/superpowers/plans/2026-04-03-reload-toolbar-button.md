# Reload Toolbar Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Reload" toolbar button (and F5 shortcut) to `MainWindow` that calls `_reload()` to refresh the commit graph, branches, and stashes.

**Architecture:** Add a `QToolBar` to `MainWindow` with a single `QAction`. Connect `triggered` to the existing `_reload()` method. No new files, no new layers touched.

**Tech Stack:** Python 3.13, PySide6 6.11, pytest, pytest-qt

---

## File Map

| File | Change |
|------|--------|
| `git_gui/presentation/main_window.py` | Add `QToolBar` + `QAction("Reload")` wired to `_reload()` |

---

## Task 1: Add reload toolbar to MainWindow

**Files:**
- Modify: `git_gui/presentation/main_window.py`

This task is UI-only. `_reload()` is already tested via signal paths, so no new test is needed. We verify by running the full suite to confirm no regressions.

- [ ] **Step 1: Update the imports in `main_window.py`**

Add `QAction`, `QKeySequence`, and `QToolBar` to the PySide6 imports. The full updated import block:

```python
from __future__ import annotations
from PySide6.QtCore import Qt, QKeySequence
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QSplitter, QToolBar
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.widgets.diff import DiffWidget
from git_gui.presentation.widgets.graph import GraphWidget
from git_gui.presentation.widgets.sidebar import SidebarWidget
```

- [ ] **Step 2: Add the toolbar in `__init__`, before `self._reload()`**

Insert these four lines immediately after `splitter.setSizes([220, 560, 620])` and before `self.setCentralWidget(splitter)`:

```python
toolbar = QToolBar("Main")
reload_action = QAction("Reload", self)
reload_action.setShortcut(QKeySequence(Qt.Key_F5))
reload_action.triggered.connect(self._reload)
toolbar.addAction(reload_action)
self.addToolBar(toolbar)
```

The full updated `__init__` after both steps:

```python
def __init__(self, queries: QueryBus, commands: CommandBus, repo_path: str, parent=None) -> None:
    super().__init__(parent)
    self.setWindowTitle(f"git gui — {repo_path}")
    self.resize(1400, 800)

    self._commands = commands
    self._sidebar = SidebarWidget(queries, commands)
    self._graph = GraphWidget(queries, commands)
    self._diff = DiffWidget(queries, commands)

    splitter = QSplitter(Qt.Horizontal)
    splitter.addWidget(self._sidebar)
    splitter.addWidget(self._graph)
    splitter.addWidget(self._diff)
    splitter.setSizes([220, 560, 620])

    toolbar = QToolBar("Main")
    reload_action = QAction("Reload", self)
    reload_action.setShortcut(QKeySequence(Qt.Key_F5))
    reload_action.triggered.connect(self._reload)
    toolbar.addAction(reload_action)
    self.addToolBar(toolbar)

    self.setCentralWidget(splitter)

    # Wire cross-widget signals
    self._graph.commit_selected.connect(self._diff.load_commit)
    self._sidebar.branch_checkout_requested.connect(self._on_branch_changed)
    self._sidebar.branch_merge_requested.connect(
        lambda b: (commands.merge.execute(b), self._reload()))
    self._sidebar.branch_rebase_requested.connect(
        lambda b: (commands.rebase.execute(b), self._reload()))
    self._sidebar.branch_delete_requested.connect(
        lambda b: (commands.delete_branch.execute(b), self._reload()))
    self._sidebar.fetch_requested.connect(
        lambda r: (commands.fetch.execute(r), self._reload()))
    self._sidebar.branch_push_requested.connect(
        lambda b: (commands.push.execute("origin", b), self._reload()))

    self._reload()
```

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all 63 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add git_gui/presentation/main_window.py
git commit -m "feat: add reload toolbar button with F5 shortcut"
```

---

## Self-Review

**Spec coverage:**
- ✅ `QToolBar` added to `MainWindow`
- ✅ `QAction("Reload")` with F5 shortcut
- ✅ Connected to `_reload()` (refreshes graph + sidebar)

**Placeholder scan:** None.

**Type consistency:** N/A — single task, no cross-task types.
