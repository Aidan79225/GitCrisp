# Delete Remote Branch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sidebar context-menu action that deletes a remote branch via `git push <remote> --delete <branch>`, following the existing `delete_remote_tag` pattern end-to-end.

**Architecture:** One new public method on each of four layers — infrastructure (`BranchOps`), domain (`IRepositoryWriter`), application (`DeleteRemoteBranch`), and presentation (sidebar signal + menu action + `BranchFlowsMixin` handler). Execution serialized through the existing `_run_remote_op` queue with a `QMessageBox` confirmation gate.

**Tech Stack:** Python 3.13, PySide6 (Qt), pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-22-delete-remote-branch-design.md`

---

## File Structure

**Modified files:**
- `git_gui/infrastructure/pygit2/branch_ops.py` — add `delete_remote_branch` method.
- `git_gui/domain/ports.py` — add to `IRepositoryWriter`.
- `git_gui/application/commands.py` — add `DeleteRemoteBranch` class.
- `git_gui/presentation/bus.py` — import and register `DeleteRemoteBranch` on `CommandBus`.
- `git_gui/presentation/widgets/sidebar.py` — new signal + Delete menu item on remote-branch rows.
- `git_gui/presentation/main_window/branch_flows.py` — new handler + wire the signal.
- `tests/presentation/widgets/test_sidebar_signals.py` — two new menu-emission tests.

**Not touched:** working-tree widget, graph, diff widget, theme, README.

---

## Task 1: Infrastructure + domain + application wiring

Bottom-up wiring. All four code changes land in one commit because they're a mechanical rippling of the same symbol through the layers, and none of them is independently useful.

**Files:**
- Modify: `git_gui/infrastructure/pygit2/branch_ops.py`
- Modify: `git_gui/domain/ports.py`
- Modify: `git_gui/application/commands.py`
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Add the method to `BranchOps`**

In `git_gui/infrastructure/pygit2/branch_ops.py`, find `delete_branch` (currently at line 92):

```python
    def delete_branch(self, name: str) -> None:
        self._repo.branches.local[name].delete()
```

Immediately after that method, insert:

```python
    def delete_remote_branch(self, remote: str, branch: str) -> None:
        """Delete a branch on the remote via `git push <remote> --delete <branch>`."""
        self._run_git("push", remote, "--delete", branch)
```

`self._run_git` resolves via MRO to `RemoteOps` — no import change needed.

- [ ] **Step 2: Add to `IRepositoryWriter`**

In `git_gui/domain/ports.py`, find the existing `delete_remote_tag` declaration (currently at line 66):

```python
    def delete_remote_tag(self, remote: str, name: str) -> None: ...
```

Immediately above that line, insert:

```python
    def delete_remote_branch(self, remote: str, branch: str) -> None: ...
```

This clusters the remote-prefixed methods together.

- [ ] **Step 3: Add `DeleteRemoteBranch` command class**

In `git_gui/application/commands.py`, find the existing `DeleteRemoteTag` (currently at line 94):

```python
class DeleteRemoteTag:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, remote: str, name: str) -> None:
        self._writer.delete_remote_tag(remote, name)
```

Immediately above it, insert:

```python
class DeleteRemoteBranch:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, remote: str, branch: str) -> None:
        self._writer.delete_remote_branch(remote, branch)


```

(Two blank lines after the new class — preserve PEP 8 spacing between top-level classes.)

- [ ] **Step 4: Register on `CommandBus`**

In `git_gui/presentation/bus.py`, find the import block for commands (currently around lines 14-31). Locate the line:

```python
    CreateTag, DeleteTag, PushTag, DeleteRemoteTag,
```

Add `DeleteRemoteBranch` to the `DeleteBranch` import line (currently line 16):

```python
    Checkout, CheckoutCommit, CheckoutRemoteBranch, CreateBranch, DeleteBranch, DeleteRemoteBranch,
```

Then in `CommandBus` (dataclass, around line 94), find `delete_branch: DeleteBranch` (line 102) and add the new attribute just below it:

```python
    delete_branch: DeleteBranch
    delete_remote_branch: DeleteRemoteBranch
```

Then in `CommandBus.from_writer` (around line 148), find `delete_branch=DeleteBranch(writer),` (line 157) and add below:

```python
            delete_branch=DeleteBranch(writer),
            delete_remote_branch=DeleteRemoteBranch(writer),
```

- [ ] **Step 5: Sanity check — run the full suite**

Run: `uv run pytest tests/ -q`

Expected: **540 passed**. This verifies the port / command / bus additions don't break any existing wiring. No new behavior yet — UI changes come in Task 2.

- [ ] **Step 6: Commit**

```bash
git add git_gui/infrastructure/pygit2/branch_ops.py git_gui/domain/ports.py git_gui/application/commands.py git_gui/presentation/bus.py
git commit -m "feat(infra): add delete_remote_branch across all four layers"
```

---

## Task 2: Sidebar menu action + signal (TDD)

Add the Delete action to the remote-branch row's context menu and the new signal that carries `(remote, branch)`. Two regression tests via the existing `_capture_menu_actions` helper.

**Files:**
- Modify: `git_gui/presentation/widgets/sidebar.py`
- Modify: `tests/presentation/widgets/test_sidebar_signals.py`

- [ ] **Step 1: Write the failing tests**

Open `tests/presentation/widgets/test_sidebar_signals.py`. After the existing `test_tag_delete_menu_emits_tag_name` (near the bottom of the file, before `test_set_buses_none_clears_model`), append these two tests:

```python
# -- 7. Context menu: remote-branch delete emits remote and branch -----


def test_remote_branch_delete_menu_emits_remote_and_branch(sidebar, qtbot):
    w, _, _ = sidebar
    item = _remote_branch_item("origin/feature", "abc123")
    _add_section(w, "REMOTE BRANCHES", [item])

    actions = _capture_menu_actions(w, item)
    assert "Delete" in actions

    with qtbot.waitSignal(w.remote_branch_delete_requested, timeout=1000) as blocker:
        actions["Delete"].trigger()
    assert blocker.args == ["origin", "feature"]


def test_remote_branch_delete_handles_slash_in_branch_name(sidebar, qtbot):
    """Branch names containing '/' must be preserved after splitting off
    the remote prefix (e.g. origin/feature/foo → remote=origin, branch=feature/foo)."""
    w, _, _ = sidebar
    item = _remote_branch_item("origin/feature/foo", "abc123")
    _add_section(w, "REMOTE BRANCHES", [item])

    actions = _capture_menu_actions(w, item)

    with qtbot.waitSignal(w.remote_branch_delete_requested, timeout=1000) as blocker:
        actions["Delete"].trigger()
    assert blocker.args == ["origin", "feature/foo"]
```

- [ ] **Step 2: Run the tests to confirm red**

Run: `uv run pytest tests/presentation/widgets/test_sidebar_signals.py::test_remote_branch_delete_menu_emits_remote_and_branch tests/presentation/widgets/test_sidebar_signals.py::test_remote_branch_delete_handles_slash_in_branch_name -v`

Expected: both tests FAIL with `AttributeError: 'SidebarWidget' object has no attribute 'remote_branch_delete_requested'`.

- [ ] **Step 3: Add the signal to `SidebarWidget`**

Open `git_gui/presentation/widgets/sidebar.py`. Find the signal declarations (near the top of `class SidebarWidget`, around line 98):

```python
    tag_delete_requested = Signal(str)       # tag name
    tag_push_requested = Signal(str)         # tag name
```

Immediately after `tag_push_requested`, add:

```python
    remote_branch_delete_requested = Signal(str, str)  # (remote, branch)
```

- [ ] **Step 4: Add the Delete menu action**

In `git_gui/presentation/widgets/sidebar.py`, find the `_show_context_menu` method's `remote_branch` branch (currently at lines 297-300):

```python
        elif kind == "remote_branch":
            remote = value.split("/")[0]
            menu.addAction("Fetch").triggered.connect(
                lambda: self.fetch_requested.emit(remote))
```

Replace the entire `elif kind == "remote_branch":` block with:

```python
        elif kind == "remote_branch":
            remote, branch = value.split("/", 1)
            menu.addAction("Fetch").triggered.connect(
                lambda: self.fetch_requested.emit(remote))
            menu.addSeparator()
            menu.addAction("Delete").triggered.connect(
                lambda: self.remote_branch_delete_requested.emit(remote, branch))
```

Why `split("/", 1)`: remote names don't contain `/`, but branch names may. `split("/", 1)` gives `["origin", "feature/foo"]` rather than `["origin", "feature", "foo"]`.

- [ ] **Step 5: Run the new tests to confirm green**

Run: `uv run pytest tests/presentation/widgets/test_sidebar_signals.py -v`

Expected: **12 passed** (10 existing + 2 new).

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest tests/ -q`

Expected: **542 passed** (540 after Task 1 + 2 new).

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/widgets/sidebar.py tests/presentation/widgets/test_sidebar_signals.py
git commit -m "feat(sidebar): add Delete action to remote-branch context menu"
```

---

## Task 3: Wire the signal in `BranchFlowsMixin`

Add the handler that confirms with a dialog and dispatches through the remote-op queue. This is what actually causes the `git push --delete` to run.

**Files:**
- Modify: `git_gui/presentation/main_window/branch_flows.py`

- [ ] **Step 1: Wire the signal**

Open `git_gui/presentation/main_window/branch_flows.py`. Find `_wire_branch_flow_signals` (currently lines 13-19):

```python
    def _wire_branch_flow_signals(self) -> None:
        self._sidebar.branch_checkout_requested.connect(self._on_branch_changed)
        self._sidebar.branch_delete_requested.connect(self._on_delete_branch)
        self._graph.delete_branch_requested.connect(self._on_delete_branch)
        self._graph.create_branch_requested.connect(self._on_create_branch)
        self._graph.checkout_commit_requested.connect(self._on_checkout_commit)
        self._graph.checkout_branch_requested.connect(self._on_checkout_branch)
```

Add one line — preserve existing lines and insert the new one after the existing `branch_delete_requested` wiring:

```python
    def _wire_branch_flow_signals(self) -> None:
        self._sidebar.branch_checkout_requested.connect(self._on_branch_changed)
        self._sidebar.branch_delete_requested.connect(self._on_delete_branch)
        self._sidebar.remote_branch_delete_requested.connect(self._on_delete_remote_branch)
        self._graph.delete_branch_requested.connect(self._on_delete_branch)
        self._graph.create_branch_requested.connect(self._on_create_branch)
        self._graph.checkout_commit_requested.connect(self._on_checkout_commit)
        self._graph.checkout_branch_requested.connect(self._on_checkout_branch)
```

- [ ] **Step 2: Add the `_on_delete_remote_branch` handler**

In the same file, find `_on_delete_branch` (currently lines 31-38):

```python
    def _on_delete_branch(self, branch: str) -> None:
        try:
            self._commands.delete_branch.execute(branch)
            self._log_panel.log(f"Deleted branch: {branch}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Delete branch {branch} — ERROR: {e}")
        self._reload()
```

Immediately after this method, insert:

```python
    def _on_delete_remote_branch(self, remote: str, branch: str) -> None:
        reply = QMessageBox.question(
            self,
            "Delete Remote Branch",
            f"Delete remote branch `{remote}/{branch}`? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._run_remote_op(
            f"Delete {remote}/{branch}",
            lambda: self._commands.delete_remote_branch.execute(remote, branch),
        )
```

`QMessageBox` is already imported at the top of the file (line 3). `self._run_remote_op` resolves via MRO to `RemoteOpQueueMixin`.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest tests/ -q`

Expected: **542 passed** (same as end of Task 2 — Task 3 adds only wiring, no new tests).

Key tests to verify still green: `tests/presentation/test_main_window_session_factory.py`, `tests/presentation/test_main_window_checkout_conflict.py`, and the 12 sidebar tests.

- [ ] **Step 4: Manual smoke check (optional, skip if headless)**

Run: `uv run python main.py`

Open a repo that has a remote with at least one branch. Right-click a remote-branch row in the sidebar (e.g., `origin/feature`). A context menu should appear with "Fetch" and "Delete" separated by a divider. Clicking "Delete" should show a confirmation dialog. Declining should do nothing; accepting should enqueue a `Delete origin/feature` remote-op visible in the status bar / log panel, and after the push completes the row should disappear from the sidebar on the next auto-reload.

If running headless, skip this step and rely on the full test suite result.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/main_window/branch_flows.py
git commit -m "feat(main_window): wire remote-branch delete to the remote-op queue"
```

---

## Done

After Task 3, the feature is complete. Final state:

- Right-click a remote-branch row in the sidebar → Delete → confirm → `git push origin --delete <branch>` runs on the remote-op queue.
- Three implementation commits (Tasks 1, 2, 3) — bisectable.
- 542 tests pass (540 baseline + 2 new).
- Zero changes to local-branch delete, graph context menu, or any other layer than the six files listed.
