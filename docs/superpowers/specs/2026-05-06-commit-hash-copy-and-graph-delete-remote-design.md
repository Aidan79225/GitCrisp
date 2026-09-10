# Click commit hash to copy + graph context menu deletes remote branch

## Context

Two unrelated UX gaps surfaced during day-to-day use:

1. **The full commit hash on the commit detail panel is read-only**.
   Users frequently need to paste a hash into a chat, an issue, or
   another git command. Right now they have to retype or screenshot
   it. Making the hash clickable to copy is a small ergonomic win.
2. **The graph's right-click menu can delete a local branch but not
   a remote branch**. The same delete already exists in the sidebar
   context menu, plus full infrastructure (`delete_remote_branch`,
   `_on_delete_remote_branch` with confirmation, `_run_remote_op`).
   The graph entry just needs to wire to the existing handler.

Both changes are small, additive, and independent. They share a PR
because they're both UX paper-cuts touching the same general area
(commit context, graph operations).

## Scope

- **Modify:** `git_gui/presentation/widgets/commit_detail.py` — add
  hit-testing for the OID rect, a new `commit_oid_copy_requested`
  signal, and underlined-font rendering for the hash.
- **Modify:** `git_gui/presentation/widgets/graph.py` — add a
  remote-branch delete block to `_show_context_menu`, plus a new
  `remote_branch_delete_requested` signal.
- **Modify:** `git_gui/presentation/main_window/branch_flows.py` —
  one new line wiring `_graph.remote_branch_delete_requested` to the
  existing `_on_delete_remote_branch` handler. Plus a new handler
  `_on_commit_oid_copy_requested` for Feature 1.
- **Modify:** `git_gui/presentation/main_window/main_window.py` (or
  the right wiring location) — one new line connecting
  `_commit_detail.commit_oid_copy_requested` to the new handler.
- **Add tests:** unit tests for both features in
  `tests/presentation/widgets/`.

## Feature 1 — Click commit hash to copy

### CommitDetailWidget changes

The widget paints everything via `painter.drawText` — there's no
QLabel to attach an event handler to. The fix is hit-testing.

1. **Track the OID rect during paint.** In `paintEvent`, after
   drawing the hash on line 93, save the bounding rect:
   ```python
   self._oid_rect = QRect(x, y, fm.horizontalAdvance(c.oid), line_h)
   ```
   Cleared on `clear()` and reset to `None` when there's no commit.
2. **Underlined font for the hash.** Construct a `QFont` from
   `painter.font()`, call `setUnderline(True)`, paint the OID with
   it, then restore the original font for the rest of the line.
   Visual affordance that the hash is interactive.
3. **`setMouseTracking(True)` in `__init__`.** Override
   `mouseMoveEvent` to switch the cursor:
   - If `self._oid_rect is not None and self._oid_rect.contains(event.pos())`:
     `setCursor(Qt.PointingHandCursor)`.
   - Otherwise: `setCursor(Qt.ArrowCursor)`.
4. **Override `mousePressEvent`.** If left-click and the position is
   in `_oid_rect`, emit:
   ```python
   commit_oid_copy_requested = Signal(str)  # full 40-char OID
   ```
   then `event.accept()`. Otherwise call `super().mousePressEvent`.
5. **Override `leaveEvent`.** Reset cursor to `Qt.ArrowCursor` when
   the mouse leaves the widget — otherwise the pointing-hand can
   persist after the user drags away.

### DiffWidget signal forwarding

`DiffWidget` already follows a forwarding pattern for child-widget
signals (see `submodule_open_requested`). Add an analogous forward:

```python
# in DiffWidget class definition:
commit_oid_copy_requested = Signal(str)

# in __init__, alongside other signal wires:
self._detail.commit_oid_copy_requested.connect(
    self.commit_oid_copy_requested.emit
)
```

This keeps `MainWindow` from reaching through `self._diff._detail`
and matches the existing convention.

### MainWindow side

A new flow handler in a new `commit_flows.py` mixin (single-purpose,
follows the existing `branch_flows.py` / `remote_op_queue.py`
pattern):

```python
class CommitFlowsMixin:
    def _wire_commit_flow_signals(self) -> None:
        self._diff.commit_oid_copy_requested.connect(
            self._on_commit_oid_copy_requested
        )

    def _on_commit_oid_copy_requested(self, oid: str) -> None:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(oid)
        self.statusBar().showMessage(f"Copied {oid[:7]}", 2000)
```

Add `CommitFlowsMixin` to `MainWindow`'s base class list and call
`_wire_commit_flow_signals()` from `__init__`.

### Tests

- `test_clicking_oid_emits_copy_signal` — construct
  `CommitDetailWidget`, call `set_commit(commit, refs)`, force a
  paint, simulate `mousePressEvent` at the OID rect's center,
  assert the signal fires with `commit.oid`.
- `test_clicking_outside_oid_does_not_emit` — same setup, click
  outside `_oid_rect`, assert no signal.
- `test_oid_rect_is_none_before_set_commit` — fresh widget, assert
  `_oid_rect is None`. Confirms initial-state handling.

## Feature 2 — Graph context menu deletes remote branch

### GraphWidget changes

In `_show_context_menu` (line 580), after the existing local-branch
block:

```python
remote_branches = [n for n in real_branches if n not in local_set]
if remote_branches:
    if len(remote_branches) == 1:
        name = remote_branches[0]
        menu.addAction(f"Delete remote branch: {name}").triggered.connect(
            lambda: self._emit_remote_delete(name)
        )
    else:
        sub = menu.addMenu("Delete remote branch")
        for name in remote_branches:
            sub.addAction(name).triggered.connect(
                lambda _checked=False, n=name: self._emit_remote_delete(n)
            )
```

New helper that splits the qualified name and emits:

```python
def _emit_remote_delete(self, name: str) -> None:
    if "/" not in name:
        return  # malformed — bail defensively
    remote, branch = name.split("/", 1)
    if not remote or not branch:
        return
    self.remote_branch_delete_requested.emit(remote, branch)
```

New signal at the class level:

```python
remote_branch_delete_requested = Signal(str, str)  # (remote, branch)
```

### MainWindow side

In `branch_flows.py:_wire_branch_flow_signals`, add one line:

```python
self._graph.remote_branch_delete_requested.connect(self._on_delete_remote_branch)
```

`_on_delete_remote_branch` (line 41) already shows a confirmation
dialog and routes through `_run_remote_op`. The graph entry inherits
this — no behavior duplication, no separate confirmation.

### Tests

- `test_context_menu_includes_delete_remote_branch_for_remote_only_row`
  — construct a graph with a row carrying a single remote branch
  (e.g., `origin/main` with no local `main`), invoke
  `_show_context_menu`, assert the menu has an action with text
  "Delete remote branch: origin/main".
- `test_emit_remote_delete_splits_remote_and_branch` — call
  `_emit_remote_delete("origin/feature/foo")` directly with a signal
  spy, assert `(remote="origin", branch="feature/foo")`.
- `test_emit_remote_delete_bails_on_malformed_name` — call with
  `"no-slash"`, assert no signal emitted.
- `test_row_with_both_local_and_remote_shows_both_delete_entries` —
  row with both `main` (local) and `origin/main` (remote), assert
  the menu has both entries.

## Edge cases

- **Slash inside branch names** (e.g., `origin/feature/foo`).
  Handled by `split("/", 1)`. Remote is `origin`, branch is
  `feature/foo`.
- **Remote name with no `/` at all** (very unusual). The
  `_emit_remote_delete` helper bails. Menu entry can still appear
  (since the name comes from `branch_names`), but clicking is a
  no-op. Acceptable; this case shouldn't arise from a healthy repo.
- **No status bar** (running widget tests headless). The
  `MainWindow.statusBar()` always exists for `QMainWindow`. The
  widget unit tests don't go through MainWindow; they only assert
  the signal — no status-bar dependency.
- **Hash hit-test misses on first commit load**. The OID rect is
  stored at the end of the first `paintEvent`. Before paint, the
  widget exists but the rect is `None`, so clicks do nothing.
  Defensive null-check in `mousePressEvent`/`mouseMoveEvent`.

## Critical files

- `git_gui/presentation/widgets/commit_detail.py` — the widget edit
  (Feature 1 widget side).
- `git_gui/presentation/widgets/diff.py` — forward
  `commit_oid_copy_requested` from `_detail` (Feature 1 forwarding).
- `git_gui/presentation/widgets/graph.py` — context menu + signal
  (Feature 2 widget side).
- `git_gui/presentation/main_window/branch_flows.py` — graph signal
  wire-up (Feature 2).
- `git_gui/presentation/main_window/commit_flows.py` — **new** —
  Feature 1 handler.
- `git_gui/presentation/main_window/main_window.py` — register new
  `CommitFlowsMixin`.
- `tests/presentation/widgets/test_commit_detail.py` — **new** —
  Feature 1 tests.
- `tests/presentation/widgets/test_graph.py` — Feature 2 tests
  appended.

Files **not** changed:
- `infrastructure/pygit2/branch_ops.py:delete_remote_branch` — existing
  command works as-is.
- `application/commands.py` and `presentation/bus.py` — bus is already
  wired for `delete_remote_branch`.
- `domain/ports.py` — no new port.

## Verification

**Automated:**
```
uv run pytest tests/presentation/widgets/test_commit_detail.py -v
uv run pytest tests/presentation/widgets/test_graph.py -v
uv run pytest tests/ -q
```

**Manual:**

Feature 1:
1. `uv run python main.py`. Open a repo, click any commit.
2. Hover the commit hash on the "Commit:" line. Cursor changes to a
   pointing hand; the hash is underlined.
3. Click. Status bar briefly shows "Copied <short_oid>". Paste into
   another app to confirm the full 40-char hash is on the clipboard.
4. Move the cursor away — cursor returns to arrow.

Feature 2:
1. With a repo that has at least one remote-only branch
   (e.g., `origin/some-feature` not yet checked out locally).
2. Right-click the commit row carrying that remote branch.
3. Confirm "Delete remote branch: origin/some-feature" appears in
   the menu.
4. Click it. Confirmation dialog appears. Cancel — no change.
5. Right-click again, click delete, confirm. Status bar shows the
   running op; on success, the branch disappears from the sidebar.
6. Repeat with a row that has both a local `main` and `origin/main`
   to confirm both delete entries appear and route to the right
   handlers.

## Branch & PR

- **Branch:** `feat/commit-hash-copy-and-graph-delete-remote`.
- **Two commits**, one per feature:
  - `feat(commit-detail): copy commit hash on click`
  - `feat(graph): delete remote branch from context menu`
- **PR:** single PR with a brief summary of both features.
