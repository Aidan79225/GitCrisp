# Stash Click-to-View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking a stash in the sidebar shows its file list and diff in the right panel's DiffWidget, with mutual exclusion between stash and graph selection.

**Architecture:** Add a `stash_clicked` signal to SidebarWidget, a `clear_selection()` method to GraphWidget, and wire them through MainWindow. The stash oid is passed to the existing `DiffWidget.load_commit(oid)` — no domain/infrastructure changes needed.

**Tech Stack:** Python, PySide6, pygit2

---

### Task 1: Sidebar emits stash oid on click

**Files:**
- Modify: `git_gui/presentation/widgets/sidebar.py:43-53` (signals), `128-130` (stash section), `152-155` (_on_click)

- [ ] **Step 1: Add `stash_clicked` signal and `clear_stash_selection` method**

In `sidebar.py`, add the signal to the class and the clear method:

```python
# Add to signal declarations (after stash_drop_requested line 52):
stash_clicked = Signal(str)              # stash oid
```

```python
# Add method to SidebarWidget class (after reload method):
def clear_stash_selection(self) -> None:
    self._tree.clearSelection()
    self._tree.setCurrentIndex(self._model.index(-1, 0))
```

- [ ] **Step 2: Pass stash oid to tree items**

Change the stash section in `_on_load_done` (line 128-130) to include the oid as the 4th tuple element:

```python
# Stashes
self._add_section("STASHES", [
    (s.message, str(s.index), "stash", s.oid) for s in stashes
])
```

- [ ] **Step 3: Emit `stash_clicked` in `_on_click`**

Replace the `_on_click` method (lines 152-155):

```python
def _on_click(self, index) -> None:
    kind = index.data(Qt.UserRole + 1)
    oid = index.data(_TARGET_OID_ROLE)
    if kind == "stash" and oid:
        self.stash_clicked.emit(oid)
    elif oid:
        self.branch_clicked.emit(oid)
```

- [ ] **Step 4: Commit**

```bash
git add git_gui/presentation/widgets/sidebar.py
git commit -m "feat: sidebar emits stash_clicked signal with stash oid"
```

---

### Task 2: Graph exposes clear_selection

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py`

- [ ] **Step 1: Add `clear_selection` method to GraphWidget**

Add this method to the `GraphWidget` class:

```python
def clear_selection(self) -> None:
    self._view.clearSelection()
    self._view.setCurrentIndex(self._model.index(-1, 0))
```

- [ ] **Step 2: Commit**

```bash
git add git_gui/presentation/widgets/graph.py
git commit -m "feat: graph widget exposes clear_selection method"
```

---

### Task 3: Wire signals in MainWindow

**Files:**
- Modify: `git_gui/presentation/main_window.py:89-109` (signal wiring), `143-150` (_on_commit_selected)

- [ ] **Step 1: Connect `stash_clicked` signal**

Add this line in `__init__` after the existing `stash_drop_requested` connection (after line 109):

```python
self._sidebar.stash_clicked.connect(self._on_stash_clicked)
```

- [ ] **Step 2: Add `_on_stash_clicked` handler**

Add this method to MainWindow:

```python
def _on_stash_clicked(self, oid: str) -> None:
    self._graph.clear_selection()
    self._right_stack.setCurrentIndex(0)
    self._diff.load_commit(oid)
```

- [ ] **Step 3: Clear stash selection on graph commit click**

In the existing `_on_commit_selected` method (line 143), add `clear_stash_selection` as the first line:

```python
def _on_commit_selected(self, oid: str) -> None:
    self._sidebar.clear_stash_selection()
    self._selected_oid = oid
    if oid == WORKING_TREE_OID:
        self._right_stack.setCurrentIndex(1)
        self._working_tree.reload()
    else:
        self._right_stack.setCurrentIndex(0)
        self._diff.load_commit(oid)
```

- [ ] **Step 4: Commit**

```bash
git add git_gui/presentation/main_window.py
git commit -m "feat: wire stash click to show stash content in diff panel"
```

---

### Task 4: Manual smoke test

- [ ] **Step 1: Run the app and verify**

```bash
cd C:/Users/Aidan/GitStack && uv run python main.py
```

Test the following:
1. Create a stash if none exist (make a change, then stash it)
2. Click a stash in the sidebar — right panel should show file list and diff, graph should have no selection
3. Click a commit in the graph — stash highlight in sidebar should clear, right panel shows the commit's content
4. Click the stash again — graph deselects, stash content shows again
