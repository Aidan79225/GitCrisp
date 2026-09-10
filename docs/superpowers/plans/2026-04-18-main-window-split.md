# MainWindow Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break `git_gui/presentation/main_window.py` (969 LOC, 69 methods, 51 `_on_*` handlers) into ten focused mixin modules under a new `git_gui/presentation/main_window/` subpackage. Mechanical move — external API and user-visible behavior unchanged.

**Architecture:** `MainWindow(QMainWindow, <ten mixins>)`. Each mixin class holds the handlers for one concern plus a `_wire_<concern>_signals()` helper that makes its own signal → slot connections. `MainWindow.__init__` builds widgets then calls each mixin's wiring helper in a fixed order. Shared instance state (`_queries`, `_commands`, `_repo_path`, `_remote_running`, `_selected_oid`, widget refs) stays on the composite.

**Tech Stack:** Python 3.13, PySide6 (Qt), pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-18-main-window-split-design.md`

---

## File Structure (end state)

```
git_gui/presentation/main_window/
├── __init__.py                           # re-exports MainWindow
├── main_window.py                        # composite class — __init__ + _build_* only
├── reload_coordinator.py                 # ReloadCoordinatorMixin
├── repo_lifecycle.py                     # RepoLifecycleMixin + _RepoReadySignals
├── remote_op_queue.py                    # RemoteOpQueueMixin + _RemoteSignals
├── branch_flows.py                       # BranchFlowsMixin
├── merge_rebase_flows.py                 # MergeRebaseFlowsMixin
├── cherry_pick_revert_flows.py           # CherryPickRevertFlowsMixin
├── reset_flow.py                         # ResetFlowMixin
├── tag_flows.py                          # TagFlowsMixin
├── stash_flows.py                        # StashFlowsMixin
└── right_panel.py                        # RightPanelMixin
```

Deleted: `git_gui/presentation/main_window.py` (the flat file).
New test: `tests/presentation/test_main_window_package.py`.
Not touched: `main.py` (same dotted import path resolves via subpackage `__init__.py`), child widgets, domain, application, infrastructure.

---

## Mixin-Extraction Pattern (repeated for Tasks 3–12)

Every mixin extraction task follows this four-step pattern. Reading it once keeps the per-task entries short.

1. **Create the mixin file** at `git_gui/presentation/main_window/<concern>.py`:

   ```python
   # git_gui/presentation/main_window/<concern>.py
   from __future__ import annotations
   # only imports that the moved method bodies reference

   class <Concern>Mixin:
       """<One-line docstring of the concern.>

       Mixin — not instantiable on its own. Relies on composite-provided
       attributes (self._queries, self._commands, widget refs, ...) set
       up by MainWindow's __init__.
       """

       def _wire_<concern>_signals(self) -> None:
           # Move every `signal.connect(...)` line from MainWindow.__init__
           # that routes into this mixin's handlers.
           ...

       # Methods copied VERBATIM from MainWindow body.
       ...
   ```

2. **Update `MainWindow`'s base tuple and `__init__`** in `git_gui/presentation/main_window.py` (the flat file during Tasks 3–11; the subpackage's `main_window.py` during Task 12):
   - Add `from git_gui.presentation.main_window.<concern> import <Concern>Mixin` near the top.
   - Append `<Concern>Mixin` to the class base tuple.
   - In `__init__`, after the `_build_*` helper calls, add `self._wire_<concern>_signals()` in the documented slot.
   - Remove the corresponding `signal.connect(...)` lines that the mixin's `_wire_*_signals` now owns — this avoids double-connecting.

3. **Delete the moved method bodies** from the `MainWindow` class body. Only the methods listed in the task — leave `__init__`, `_build_*`, and as-yet-unextracted methods alone.

4. **Run the full suite:** `uv run pytest tests/ -q`. Expected: **502 passed, 0 failed** (baseline from the latest master). Regression means (a) a method was partially deleted, (b) a signal was dropped, (c) a signal was connected twice (handler fires twice), or (d) an import is missing.

**Copying discipline:**
- Copy method bodies via Read + Write. Do not retype. Do not reformat. Docstrings and inline comments preserved.
- When moving `signal.connect(...)` lines, copy them verbatim including lambdas. Do not reorder within the `_wire_*_signals` body — preserve the order they appeared in `__init__`.

**Import discipline:**
- The plan hints at the "likely" imports each mixin will need. Bodies may reference additional modules (`logging`, `subprocess`, `threading`, `QMessageBox`, `QInputDialog`, dialog classes, etc.). Include every import the bodies actually reference.
- Mixin files MUST NOT import `MainWindow` (circular).

---

## Task 1: Carve `__init__` into `_build_*` helpers (single-file refactor)

Before any mixin extraction, split the monolithic `MainWindow.__init__` into four phase helpers and leave signal wiring inline as the remaining body. No new files, no behavior change. The existing `main_window.py` stays flat.

**Files:**
- Modify: `git_gui/presentation/main_window.py`

- [ ] **Step 1: Read the current `__init__`**

Open `git_gui/presentation/main_window.py` and locate `MainWindow.__init__`. Identify four phases (line ranges will vary):
- **Chrome:** `setWindowTitle`, `resize`, menubar styling, `install_appearance_menu`.
- **Widgets:** construction of `_sidebar`, `_graph`, `_diff`, `_working_tree`, `_repo_list`, `_log_panel`, `_right_stack`, helper state (`_remote_running`, `_selected_oid`, `_repo_ready_signals`).
- **Layout:** `sidebar_splitter`, horizontal `splitter`, handle disabling, `central` QWidget + its vertical layout, `setCentralWidget`.
- **Shortcuts:** every `QShortcut` construction + `install_git_menu` at the end of __init__. (Shortcuts stay in this phase even though the git menu install is technically chrome — the current file places them together; preserve that.)

The REMAINING body is signal wiring (`self._sidebar.branch_checkout_requested.connect(...)` etc.) plus the initial state setup at the very end of __init__. Leave those where they are.

- [ ] **Step 2: Extract `_build_chrome(self)` method**

Create a new method immediately after `__init__`:

```python
def _build_chrome(self) -> None:
    # paste the chrome lines here — e.g.
    self.setWindowTitle(f"GitCrisp — {self._repo_path}" if self._repo_path else "GitCrisp")
    self.resize(1400, 800)
    self.menuBar().setStyleSheet(
        "QMenu { padding: 6px; }"
        "QMenu::item { padding: 6px 24px 6px 20px; }"
    )
    install_appearance_menu(self)
```

Replace those lines in `__init__` with a single `self._build_chrome()` call.

- [ ] **Step 3: Extract `_build_widgets(self)` method**

Create a new method after `_build_chrome`. Move the widget-construction lines (everything from `self._sidebar = SidebarWidget(...)` through the construction of `_remote_running`, `_selected_oid`, and `_repo_ready_signals` wiring from sub-project A). Replace the block in `__init__` with `self._build_widgets()`.

- [ ] **Step 4: Extract `_build_layout(self)` method**

Create a new method after `_build_widgets`. Move the layout lines (sidebar_splitter, outer splitter, handle lock, `central = QWidget(); central_layout = QVBoxLayout(central); ...; setCentralWidget(central)`). Replace with `self._build_layout()`.

- [ ] **Step 5: Extract `_build_shortcuts(self)` method**

Create a new method after `_build_layout`. Move all `QShortcut` constructions and the final `install_git_menu(self, ...)` call. Replace with `self._build_shortcuts()`.

- [ ] **Step 6: Verify `__init__` now reads as four helper calls + signal wiring + initial state**

The body should look approximately like:

```python
def __init__(self, ..., *, session_factory) -> None:
    super().__init__(parent)
    # instance attributes: _queries, _commands, _repo_store, _remote_tag_cache,
    # _repo_path, _session_factory (from sub-project A)

    self._build_chrome()
    self._build_widgets()
    self._build_layout()
    self._build_shortcuts()

    # ── Signal wiring (will be split into mixins in Tasks 3–12) ─────────
    self._sidebar.branch_checkout_requested.connect(self._on_branch_changed)
    ...
    # ── Initial state (preserve whatever is currently here) ─────────────
    ...
```

If the current __init__ also has instance-attribute assignments mixed with widget construction, keep the attributes at the top (before `_build_chrome`) so `_build_*` methods see them.

- [ ] **Step 7: Run the suite**

Run: `uv run pytest tests/ -q`
Expected: **502 passed**. Visible behavior is identical — same widgets, same layout, same signals.

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/main_window.py
git commit -m "refactor(main_window): carve __init__ into _build_chrome/_widgets/_layout/_shortcuts helpers"
```

---

## Task 2: Create subpackage scaffold

Create an empty subpackage `git_gui/presentation/main_window/` — but wait, that's a name collision with the existing `main_window.py` file. Python allows either a file OR a package at a given dotted path, not both. Step around it by creating the subpackage in a separate directory during extraction and performing the directory-to-module swap at Task 12.

Because of that, **Task 2 is a no-op until Task 12**. Skip straight to Task 3.

---

## Task 3: Extract `ReloadCoordinatorMixin`

Smallest mixin. Moves `_reload` and its two signal connections. Establishes the mixin pattern for subsequent tasks.

**Files:**
- Create: `git_gui/presentation/main_window/reload_coordinator.py` (the new file lives in a new directory that coexists with the flat `main_window.py` until Task 12 — see note below).
- Modify: `git_gui/presentation/main_window.py`

**Note on coexistence:** Python's import resolution allows `git_gui/presentation/main_window.py` (flat module) and `git_gui/presentation/main_window/` (package directory) to coexist on disk, but only ONE will be found by imports — the file wins on most Python installations. To work around this for Tasks 3–11, create the mixin files under a **temporary** subpackage `git_gui/presentation/main_window_pkg/`, and in Task 12 rename `main_window_pkg/` → `main_window/` atomically with the deletion of the flat `main_window.py`.

**Per-task instructions for Tasks 3–11 use `main_window_pkg/` as the mixin directory.** Task 12 does the rename + cleanup.

**Revised file path:** Create `git_gui/presentation/main_window_pkg/reload_coordinator.py`.

**Methods to move (verbatim with full bodies):**
- `_reload(self) -> None` (central sync method, ≈20 LOC)

**Signal connections to move** from `MainWindow.__init__` into `ReloadCoordinatorMixin._wire_reload_signals()`:
- `self._working_tree.reload_requested.connect(self._reload)`
- `self._graph.reload_requested.connect(self._reload)`
- `self._reload_shortcut.activated.connect(self._reload)` — wait, this lives in `_build_shortcuts` now (Task 1). The `_build_shortcuts` method retains the F5 shortcut construction AND its `.connect(self._reload)` — that is, the F5 shortcut's connection stays with the shortcut construction, NOT in the mixin's wiring helper. Rationale: the shortcut is a widget-level wiring that belongs with shortcut construction.

Confirm by reading the current code — if `self._reload_shortcut.activated.connect(self._reload)` lives in `_build_shortcuts` after Task 1, leave it there. If it's in the main `__init__` body, move it to `_wire_reload_signals`.

**Imports for `reload_coordinator.py`:**
```python
from __future__ import annotations
```

(No other imports needed — `_reload` uses `self._sidebar`, `self._graph`, `self._working_tree`, `self._diff`, all resolved from composite.)

- [ ] **Step 1: Create `main_window_pkg/__init__.py`** as an empty file with a placeholder comment. Will be upgraded to re-export in Task 12.

```python
# git_gui/presentation/main_window_pkg/__init__.py
# Temporary subpackage — renamed to main_window/ in Task 12.
```

- [ ] **Step 2: Create `main_window_pkg/reload_coordinator.py`** with the mixin skeleton from the Mixin-Extraction Pattern and the verbatim body of `_reload` plus its `_wire_reload_signals` helper.

- [ ] **Step 3: Update `main_window.py`** (the flat file):
- Add `from git_gui.presentation.main_window_pkg.reload_coordinator import ReloadCoordinatorMixin` with the other presentation imports.
- Change class declaration `class MainWindow(QMainWindow):` → `class MainWindow(QMainWindow, ReloadCoordinatorMixin):`.
- In `__init__`, after the four `_build_*` calls, add `self._wire_reload_signals()`.
- Delete the two `signal.connect(self._reload)` lines (working_tree and graph reload_requested) from `__init__` — they are now in the mixin.
- Delete the `_reload` method body from `MainWindow`.

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/ -q`
Expected: **502 passed**.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/main_window_pkg/__init__.py git_gui/presentation/main_window_pkg/reload_coordinator.py git_gui/presentation/main_window.py
git commit -m "refactor(main_window): extract ReloadCoordinatorMixin"
```

---

## Task 4: Extract `RightPanelMixin`

Seven handlers, small LOC, includes clone/submodule flows.

**Files:**
- Create: `git_gui/presentation/main_window_pkg/right_panel.py`
- Modify: `git_gui/presentation/main_window.py`

**Methods to move (verbatim):**
- `_on_commit_selected(self, oid: str) -> None`
- `_on_working_tree_empty(self) -> None`
- `_on_stash_clicked(self, oid: str) -> None` — wait: this is a stash-specific method. Keep it in `StashFlowsMixin` (Task 7). Do NOT move it here.

Revised list:
- `_on_commit_selected`
- `_on_working_tree_empty`
- `_on_insight_requested`
- `_on_clone_requested`
- `_on_clone_completed`
- `_on_submodule_open_requested`
- `_on_submodule_path_clicked`

**Signal connections to move** into `_wire_right_panel_signals`:
- `self._graph.commit_selected.connect(self._on_commit_selected)`
- `self._working_tree.working_tree_empty.connect(self._on_working_tree_empty)`
- `self._graph.insight_requested.connect(self._on_insight_requested)`
- `self._repo_list.clone_requested.connect(self._on_clone_requested)`
- `self._diff.submodule_open_requested.connect(self._on_submodule_path_clicked)`
- `self._working_tree.submodule_open_requested.connect(self._on_submodule_path_clicked)`

Note: `_on_clone_completed` is wired inside `_on_clone_requested` (dialog signal), not in `__init__`. That's fine — the wiring happens whenever the handler is invoked.

**Imports:**
```python
from __future__ import annotations
from pathlib import Path
from git_gui.presentation.widgets.clone_dialog import CloneDialog
from git_gui.presentation.widgets.insight_dialog import InsightDialog
```

(Plus anything else the bodies reference — check `QMessageBox`, `QInputDialog`, etc.)

- [ ] **Step 1: Create `right_panel.py`** per Mixin-Extraction Pattern with the 7 methods pasted verbatim and the `_wire_right_panel_signals` body listing the six connect lines above.
- [ ] **Step 2: Update `main_window.py`** — import mixin, append to base tuple, add `self._wire_right_panel_signals()` after existing `_wire_*` calls in `__init__`, delete the six connect lines from `__init__`, delete the 7 method bodies from `MainWindow`.
- [ ] **Step 3: Run suite.** `uv run pytest tests/ -q` → 502 passed.
- [ ] **Step 4: Commit.**
```bash
git add git_gui/presentation/main_window_pkg/right_panel.py git_gui/presentation/main_window.py
git commit -m "refactor(main_window): extract RightPanelMixin"
```

---

## Task 5: Extract `ResetFlowMixin`

Single handler + dialog.

**Files:**
- Create: `git_gui/presentation/main_window_pkg/reset_flow.py`
- Modify: `git_gui/presentation/main_window.py`

**Methods to move (verbatim):**
- `_on_reset_to_commit(self, oid, default_mode) -> None`

**Signal connections to move** into `_wire_reset_flow_signals`:
- `self._graph.reset_to_commit_requested.connect(self._on_reset_to_commit)`

**Imports:**
```python
from __future__ import annotations
from git_gui.presentation.dialogs.reset_dialog import ResetDialog
# plus domain entities referenced by the body (e.g. ResetMode)
```

- [ ] **Step 1: Create `reset_flow.py`.**
- [ ] **Step 2: Update `main_window.py`** — import, base tuple, `_wire_reset_flow_signals()` call, delete connect line, delete handler body.
- [ ] **Step 3: Run suite.**
- [ ] **Step 4: Commit.**
```bash
git add git_gui/presentation/main_window_pkg/reset_flow.py git_gui/presentation/main_window.py
git commit -m "refactor(main_window): extract ResetFlowMixin"
```

---

## Task 6: Extract `StashFlowsMixin`

Five stash-related handlers.

**Files:**
- Create: `git_gui/presentation/main_window_pkg/stash_flows.py`
- Modify: `git_gui/presentation/main_window.py`

**Methods to move (verbatim):**
- `_on_stash_pop`
- `_on_stash_apply`
- `_on_stash_drop`
- `_on_stash_requested`
- `_on_stash_clicked`

**Signal connections to move** into `_wire_stash_flow_signals`:
- `self._sidebar.stash_pop_requested.connect(self._on_stash_pop)`
- `self._sidebar.stash_apply_requested.connect(self._on_stash_apply)`
- `self._sidebar.stash_drop_requested.connect(self._on_stash_drop)`
- `self._sidebar.stash_clicked.connect(self._on_stash_clicked)`
- `self._graph.stash_requested.connect(self._on_stash_requested)`

**Imports:**
```python
from __future__ import annotations
from PySide6.QtWidgets import QMessageBox
# plus anything else referenced by the bodies
```

- [ ] **Step 1: Create `stash_flows.py`.**
- [ ] **Step 2: Update `main_window.py`.**
- [ ] **Step 3: Run suite.**
- [ ] **Step 4: Commit.**
```bash
git commit -m "refactor(main_window): extract StashFlowsMixin"
```

---

## Task 7: Extract `BranchFlowsMixin`

Five handlers: branch checkout, create, delete, detached-HEAD checkout, remote-branch checkout.

**Files:**
- Create: `git_gui/presentation/main_window_pkg/branch_flows.py`
- Modify: `git_gui/presentation/main_window.py`

**Methods to move (verbatim):**
- `_on_branch_changed`
- `_on_delete_branch`
- `_on_create_branch`
- `_on_checkout_commit`
- `_on_checkout_branch`

**Signal connections to move** into `_wire_branch_flow_signals`:
- `self._sidebar.branch_checkout_requested.connect(self._on_branch_changed)`
- `self._sidebar.branch_delete_requested.connect(self._on_delete_branch)`
- `self._graph.delete_branch_requested.connect(self._on_delete_branch)`
- `self._graph.create_branch_requested.connect(self._on_create_branch)`
- `self._graph.checkout_commit_requested.connect(self._on_checkout_commit)`
- `self._graph.checkout_branch_requested.connect(self._on_checkout_branch)`

**Imports:**
```python
from __future__ import annotations
from PySide6.QtWidgets import QInputDialog, QMessageBox
# plus domain entities if referenced
```

- [ ] **Step 1: Create `branch_flows.py`.**
- [ ] **Step 2: Update `main_window.py`.**
- [ ] **Step 3: Run suite.**
- [ ] **Step 4: Commit.**
```bash
git commit -m "refactor(main_window): extract BranchFlowsMixin"
```

---

## Task 8: Extract `CherryPickRevertFlowsMixin`

Six handlers: cherry-pick + its abort/continue, revert + its abort/continue.

**Files:**
- Create: `git_gui/presentation/main_window_pkg/cherry_pick_revert_flows.py`
- Modify: `git_gui/presentation/main_window.py`

**Methods to move (verbatim):**
- `_on_cherry_pick`
- `_on_cherry_pick_abort`
- `_on_cherry_pick_continue`
- `_on_revert`
- `_on_revert_abort`
- `_on_revert_continue`

**Signal connections to move** into `_wire_cherry_pick_revert_flow_signals`:
- `self._graph.cherry_pick_requested.connect(self._on_cherry_pick)`
- `self._graph.revert_commit_requested.connect(self._on_revert)`
- `self._diff.cherry_pick_abort_requested.connect(self._on_cherry_pick_abort)`
- `self._working_tree.cherry_pick_abort_requested.connect(self._on_cherry_pick_abort)`
- `self._diff.cherry_pick_continue_requested.connect(self._on_cherry_pick_continue)`
- `self._working_tree.cherry_pick_continue_requested.connect(self._on_cherry_pick_continue)`
- `self._diff.revert_abort_requested.connect(self._on_revert_abort)`
- `self._working_tree.revert_abort_requested.connect(self._on_revert_abort)`
- `self._diff.revert_continue_requested.connect(self._on_revert_continue)`
- `self._working_tree.revert_continue_requested.connect(self._on_revert_continue)`

**Imports:**
```python
from __future__ import annotations
from PySide6.QtWidgets import QMessageBox
```

- [ ] **Step 1: Create `cherry_pick_revert_flows.py`.**
- [ ] **Step 2: Update `main_window.py`.**
- [ ] **Step 3: Run suite.**
- [ ] **Step 4: Commit.**
```bash
git commit -m "refactor(main_window): extract CherryPickRevertFlowsMixin"
```

---

## Task 9: Extract `TagFlowsMixin`

Four items: create tag, delete tag (with dual local/remote flow), and two helper methods for the dual flow.

**Files:**
- Create: `git_gui/presentation/main_window_pkg/tag_flows.py`
- Modify: `git_gui/presentation/main_window.py`

**Methods to move (verbatim):**
- `_on_create_tag`
- `_on_delete_tag`
- `_delete_tag_local_only`
- `_delete_tag_local_and_remote`

**Signal connections to move** into `_wire_tag_flow_signals`:
- `self._graph.create_tag_requested.connect(self._on_create_tag)`
- `self._sidebar.tag_delete_requested.connect(self._on_delete_tag)`
- `self._sidebar.tag_push_requested.connect(self._on_push_tag)` — wait: `_on_push_tag` lives in RemoteOpQueueMixin (Task 10). Move this connect line to `_wire_remote_op_signals` in Task 10, NOT here.

Revised list (drop the push_tag connection — it belongs with RemoteOpQueue):
- `self._graph.create_tag_requested.connect(self._on_create_tag)`
- `self._sidebar.tag_delete_requested.connect(self._on_delete_tag)`

**Cross-mixin reference note:** `_delete_tag_local_and_remote` calls `self._run_remote_op(...)`. That helper is still on `MainWindow` at this point (moves to RemoteOpQueueMixin in Task 10) and resolves via `self.` either directly or via MRO in later tasks. Works regardless of extraction order.

**Imports:**
```python
from __future__ import annotations
from PySide6.QtWidgets import QMessageBox
from git_gui.presentation.widgets.create_tag_dialog import CreateTagDialog
# plus any other imports the bodies reference
```

- [ ] **Step 1: Create `tag_flows.py`.**
- [ ] **Step 2: Update `main_window.py`.**
- [ ] **Step 3: Run suite.**
- [ ] **Step 4: Commit.**
```bash
git commit -m "refactor(main_window): extract TagFlowsMixin"
```

---

## Task 10: Extract `RemoteOpQueueMixin`

Central remote-operation serializer + push/pull/fetch/push-tag handlers + `_RemoteSignals` helper class + two small helpers.

**Files:**
- Create: `git_gui/presentation/main_window_pkg/remote_op_queue.py`
- Modify: `git_gui/presentation/main_window.py`

**Methods to move (verbatim):**
- `_run_remote_op`
- `_on_remote_done`
- `_on_remote_error`
- `_on_push`
- `_on_pull`
- `_on_fetch_all_prune`
- `_on_fetch_single`
- `_on_push_tag`
- `_get_current_branch`
- `_update_remote_tag_cache`

**Classes to move (verbatim):** `_RemoteSignals` — the QObject helper with `finished = Signal(str)` and `failed = Signal(str, str)` (or similar shape — read the current definition in `main_window.py` and copy verbatim).

**Signal connections to move** into `_wire_remote_op_signals`:
- `self._graph.push_requested.connect(self._on_push)`
- `self._graph.pull_requested.connect(self._on_pull)`
- `self._graph.fetch_all_requested.connect(self._on_fetch_all_prune)`
- `self._sidebar.fetch_requested.connect(self._on_fetch_single)`
- `self._sidebar.branch_push_requested.connect(lambda: self._run_remote_op("push", ...))` — preserve whatever lambda the current code uses; copy verbatim.
- `self._sidebar.tag_push_requested.connect(self._on_push_tag)` — moved from `_wire_tag_flow_signals` per the note in Task 9.

**Imports:**
```python
from __future__ import annotations
import threading
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox
```

- [ ] **Step 1: Create `remote_op_queue.py`** with `_RemoteSignals` at module level above the mixin class, followed by `RemoteOpQueueMixin` with its 10 methods and `_wire_remote_op_signals`.
- [ ] **Step 2: Update `main_window.py`** — remove the inline `_RemoteSignals` class definition (it moves with the mixin), remove the 10 method bodies, remove the six connect lines above, add the mixin import and base, add `self._wire_remote_op_signals()` call in `__init__`.
- [ ] **Step 3: Run suite.**
- [ ] **Step 4: Commit.**
```bash
git commit -m "refactor(main_window): extract RemoteOpQueueMixin (with _RemoteSignals + _run_remote_op)"
```

---

## Task 11: Extract `MergeRebaseFlowsMixin`

Largest flow mixin. Merge, rebase, interactive rebase, abort/continue for both.

**Files:**
- Create: `git_gui/presentation/main_window_pkg/merge_rebase_flows.py`
- Modify: `git_gui/presentation/main_window.py`

**Methods to move (verbatim):**
- `_on_merge`
- `_on_merge_commit`
- `_on_merge_abort`
- `_on_merge_continue`
- `_on_rebase`
- `_on_rebase_onto_commit`
- `_on_rebase_abort`
- `_on_rebase_continue`
- `_on_interactive_rebase_branch`
- `_on_interactive_rebase_commit`
- `_open_interactive_rebase`

**Signal connections to move** into `_wire_merge_rebase_flow_signals`:
- `self._graph.merge_branch_requested.connect(self._on_merge)`
- `self._graph.merge_commit_requested.connect(self._on_merge_commit)`
- `self._graph.rebase_onto_branch_requested.connect(self._on_rebase)`
- `self._graph.rebase_onto_commit_requested.connect(self._on_rebase_onto_commit)`
- `self._graph.interactive_rebase_branch_requested.connect(self._on_interactive_rebase_branch)`
- `self._graph.interactive_rebase_commit_requested.connect(self._on_interactive_rebase_commit)`
- `self._sidebar.branch_merge_requested.connect(self._on_merge)`
- `self._sidebar.branch_rebase_requested.connect(self._on_rebase)`
- `self._diff.merge_abort_requested.connect(self._on_merge_abort)`
- `self._working_tree.merge_abort_requested.connect(self._on_merge_abort)`
- `self._working_tree.merge_continue_requested.connect(self._on_merge_continue)`
- `self._diff.rebase_abort_requested.connect(self._on_rebase_abort)`
- `self._working_tree.rebase_abort_requested.connect(self._on_rebase_abort)`
- `self._diff.rebase_continue_requested.connect(lambda: self._on_rebase_continue(""))`
- `self._working_tree.rebase_continue_requested.connect(lambda: self._on_rebase_continue(""))`

Preserve whatever lambdas the current code uses.

**Imports:**
```python
from __future__ import annotations
from PySide6.QtWidgets import QDialog, QMessageBox
from git_gui.presentation.dialogs.merge_dialog import MergeDialog
from git_gui.presentation.dialogs.interactive_rebase_dialog import InteractiveRebaseDialog
```

(Plus anything else the bodies reference — `MergeAnalysisResult`, etc.)

- [ ] **Step 1: Create `merge_rebase_flows.py`.**
- [ ] **Step 2: Update `main_window.py`.**
- [ ] **Step 3: Run suite.**
- [ ] **Step 4: Commit.**
```bash
git commit -m "refactor(main_window): extract MergeRebaseFlowsMixin"
```

---

## Task 12: Extract `RepoLifecycleMixin` and perform the directory swap

This task has two parts. The first extracts `RepoLifecycleMixin` (the last remaining concern). The second renames `main_window_pkg/` → `main_window/` and deletes the flat `main_window.py` by moving its remaining shell (just `__init__` + `_build_*`) into `main_window/main_window.py`. After this task, the composite lives at `git_gui/presentation/main_window/main_window.py`.

**Files:**
- Create: `git_gui/presentation/main_window_pkg/repo_lifecycle.py` (before the swap)
- Rename: `git_gui/presentation/main_window_pkg/` → `git_gui/presentation/main_window/`
- Create: `git_gui/presentation/main_window/main_window.py` (moved from the flat file)
- Modify: `git_gui/presentation/main_window/__init__.py` (re-exports)
- Delete: `git_gui/presentation/main_window.py` (flat)

### Part A: Extract RepoLifecycleMixin

**Methods to move (verbatim):**
- `_switch_repo`
- `_on_repo_ready`
- `_on_repo_failed`
- `_enter_empty_state`
- `_on_repo_open`
- `_on_repo_close`
- `_close_current_repo`
- `_switch_to_repo_index`
- `_on_repo_remove_recent`

**Classes to move (verbatim):** `_RepoReadySignals` QObject helper.

**Signal connections to move** into `_wire_repo_lifecycle_signals`:
- `self._repo_list.repo_switch_requested.connect(self._switch_repo)`
- `self._repo_list.repo_open_requested.connect(self._on_repo_open)`
- `self._repo_list.repo_close_requested.connect(self._on_repo_close)`
- `self._repo_list.repo_remove_recent_requested.connect(self._on_repo_remove_recent)`
- `self._repo_ready_signals.ready.connect(self._on_repo_ready)`
- `self._repo_ready_signals.failed.connect(self._on_repo_failed)`

Note: the last two — the `_repo_ready_signals` wire-up — currently live in `__init__` (added in sub-project A). They also move to `_wire_repo_lifecycle_signals`.

**Imports:**
```python
from __future__ import annotations
import threading
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from git_gui.presentation.menus.git_menu import install_git_menu
```

(Plus anything else the bodies reference.)

- [ ] **Step A1: Create `main_window_pkg/repo_lifecycle.py`** with `_RepoReadySignals` at module level above the mixin.
- [ ] **Step A2: Update `main_window.py`** — delete the inline `_RepoReadySignals` class, delete the nine method bodies, delete the six connect lines, add the mixin import, append to base tuple, add `self._wire_repo_lifecycle_signals()` call in `__init__`.
- [ ] **Step A3: Run suite.** `uv run pytest tests/ -q` → 502 passed.

### Part B: Perform the directory swap

At this point `MainWindow` in the flat `main_window.py` consists of:
- Declaration inheriting from `QMainWindow` + all 10 mixins.
- `__init__` with attribute setup, four `_build_*` calls, ten `_wire_*` calls, and initial state.
- Four `_build_*` helper methods.

This shell is small (~100-150 LOC). Move it into the subpackage and delete the flat file.

- [ ] **Step B1: Rename the package directory**

Run: `git mv git_gui/presentation/main_window_pkg git_gui/presentation/main_window` — but this creates a collision with the flat `main_window.py`. Python's os layer refuses. Do it in two steps:

1. `git mv git_gui/presentation/main_window.py git_gui/presentation/main_window_old.py` — rename the flat file out of the way.
2. `git mv git_gui/presentation/main_window_pkg git_gui/presentation/main_window` — rename the package to its final name.
3. Proceed to Step B2.

- [ ] **Step B2: Move the shell into the subpackage**

Read `git_gui/presentation/main_window_old.py`. Copy the entire file contents to `git_gui/presentation/main_window/main_window.py`. Update the mixin imports inside so they reference the new subpackage path (`from git_gui.presentation.main_window.reload_coordinator import ReloadCoordinatorMixin`, etc. — drop the `_pkg` substring).

- [ ] **Step B3: Update each mixin's internal imports**

In each of the ten mixin files under `git_gui/presentation/main_window/`, if a mixin imports from another mixin via the temporary `main_window_pkg.` path, update those imports to `main_window.`. Most mixins will not import each other; check with Grep for any residual `main_window_pkg` references.

Run: `grep -r "main_window_pkg" git_gui/ tests/` — expect zero matches after all updates.

- [ ] **Step B4: Write `git_gui/presentation/main_window/__init__.py`**

```python
# git_gui/presentation/main_window/__init__.py
from git_gui.presentation.main_window.main_window import MainWindow

__all__ = ["MainWindow"]
```

- [ ] **Step B5: Delete the stale old flat file**

Run: `git rm git_gui/presentation/main_window_old.py`.

- [ ] **Step B6: Update any test imports that referenced `main_window_pkg`**

Grep the test tree: `grep -r "main_window_pkg" tests/`. Expect zero matches. If any tests wrote to the temporary path, update them to `main_window` (they shouldn't — the mixin files aren't directly tested).

- [ ] **Step B7: Run the full suite**

Run: `uv run pytest tests/ -q`
Expected: **502 passed**. The dotted import path `git_gui.presentation.main_window.MainWindow` still resolves — via the subpackage's `__init__.py` now instead of the flat file.

- [ ] **Step B8: Commit**

```bash
git add git_gui/presentation/main_window/
# The legacy flat file was deleted via `git rm` in Step B5.
git commit -m "refactor(main_window): extract RepoLifecycleMixin and relocate composite to subpackage"
```

---

## Task 13: Add structural tests

Two tests that guard the mixin-composite layout against future drift.

**Files:**
- Create: `tests/presentation/test_main_window_package.py`

- [ ] **Step 1: Write the structural test file**

```python
"""Structural tests for the git_gui.presentation.main_window subpackage.

Locks in the mixin-composite layout so future drift is caught:
- MainWindow is importable from the package root.
- Its MRO includes every declared mixin.
- MainWindow itself defines only __init__ + _build_* helpers + any Qt overrides.
- No _on_* or _wire_* method is defined directly on the composite — they
  must all come from mixins.
"""
from __future__ import annotations
from PySide6.QtWidgets import QMainWindow


def test_main_window_is_importable_from_package_root():
    from git_gui.presentation.main_window import MainWindow
    assert MainWindow is not None


def test_main_window_mro_includes_all_mixins():
    from git_gui.presentation.main_window import MainWindow
    from git_gui.presentation.main_window.branch_flows import BranchFlowsMixin
    from git_gui.presentation.main_window.cherry_pick_revert_flows import CherryPickRevertFlowsMixin
    from git_gui.presentation.main_window.merge_rebase_flows import MergeRebaseFlowsMixin
    from git_gui.presentation.main_window.reload_coordinator import ReloadCoordinatorMixin
    from git_gui.presentation.main_window.remote_op_queue import RemoteOpQueueMixin
    from git_gui.presentation.main_window.repo_lifecycle import RepoLifecycleMixin
    from git_gui.presentation.main_window.reset_flow import ResetFlowMixin
    from git_gui.presentation.main_window.right_panel import RightPanelMixin
    from git_gui.presentation.main_window.stash_flows import StashFlowsMixin
    from git_gui.presentation.main_window.tag_flows import TagFlowsMixin

    expected = {
        BranchFlowsMixin, CherryPickRevertFlowsMixin, MergeRebaseFlowsMixin,
        ReloadCoordinatorMixin, RemoteOpQueueMixin, RepoLifecycleMixin,
        ResetFlowMixin, RightPanelMixin, StashFlowsMixin, TagFlowsMixin,
    }
    missing = expected - set(MainWindow.__mro__)
    assert not missing, f"MainWindow MRO missing mixins: {missing}"
    assert QMainWindow in MainWindow.__mro__, "MainWindow must still inherit from QMainWindow"


def test_main_window_composite_defines_no_handlers_directly():
    """The composite must not define any _on_* or _wire_* method directly.
    All handlers and wiring come from mixins."""
    from git_gui.presentation.main_window import MainWindow

    own_names = list(vars(MainWindow).keys())
    offending = [
        n for n in own_names
        if n.startswith("_on_") or n.startswith("_wire_")
    ]
    assert offending == [], (
        f"MainWindow must not define _on_* or _wire_* methods directly; "
        f"move them to the appropriate mixin. Found: {offending}"
    )


def test_main_window_composite_body_matches_allowlist():
    """The composite may only define __init__, _build_* helpers, and Qt
    overrides (methods resolvable on QMainWindow). This prevents flow
    helpers from creeping back onto the composite."""
    from git_gui.presentation.main_window import MainWindow

    own_names = [n for n in vars(MainWindow) if not n.startswith("__")]
    allowed_prefixes = ("_build_",)
    for name in own_names:
        is_build = name.startswith(allowed_prefixes)
        is_qt_override = hasattr(QMainWindow, name)
        assert is_build or is_qt_override, (
            f"MainWindow defines '{name}' directly; "
            f"it must be either a _build_* helper or a Qt override."
        )
```

- [ ] **Step 2: Run the new tests alone**

Run: `uv run pytest tests/presentation/test_main_window_package.py -v`
Expected: **4 passed**.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest tests/ -q`
Expected: **506 passed** (502 baseline + 4 new).

- [ ] **Step 4: Commit**

```bash
git add tests/presentation/test_main_window_package.py
git commit -m "test(main_window): add structural guards for the mixin-composite layout"
```

---

## Done

After Task 13, `MainWindow` is split across ten focused mixins plus a thin composite. Final check-list:

- `git_gui/presentation/main_window/` subpackage with 10 mixins + composite + `__init__.py` re-export.
- Flat `git_gui/presentation/main_window.py` deleted.
- `main.py` unchanged (same dotted import path).
- 506 tests pass.
- Zero changes to domain, application, infrastructure, child widgets, or user-visible behavior.
