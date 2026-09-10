# Click commit hash to copy + graph delete remote branch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two unrelated UX paper-cuts: clicking the commit hash in the commit detail panel copies it to the clipboard with a status-bar toast, and right-clicking a row in the graph offers a "Delete remote branch" entry alongside the existing local-branch delete.

**Architecture:** Two TDD tasks, one per feature. Feature 1 hit-tests an OID rect inside `CommitDetailWidget` and emits a signal that flows DiffWidget → MainWindow → clipboard + status bar via a new `CommitFlowsMixin`. Feature 2 mirrors the existing local-branch delete pattern in `GraphWidget._show_context_menu` and routes the new signal to the existing `_on_delete_remote_branch` handler. No new infrastructure or domain code; signal-bridge wiring throughout.

**Tech Stack:** PySide6 (`QWidget` painted with `QPainter`, `QGuiApplication.clipboard()`, `QMenu`). Tests use `pytest-qt` (`qtbot`). Project uses `uv run` for Python and `rtk` for shell commands.

**Spec:** `docs/superpowers/specs/2026-05-06-commit-hash-copy-and-graph-delete-remote-design.md`

---

## File Structure

- **Modify:** `git_gui/presentation/widgets/commit_detail.py` — add signal, `_oid_rect` tracking, mouse handlers, underlined hash font.
- **Modify:** `git_gui/presentation/widgets/diff.py` — declare and forward `commit_oid_copy_requested`.
- **Modify:** `git_gui/presentation/widgets/graph.py` — add remote-branch delete block to `_show_context_menu`, plus signal and `_emit_remote_delete` helper.
- **Modify:** `git_gui/presentation/main_window/branch_flows.py` — wire the graph signal to the existing handler.
- **Create:** `git_gui/presentation/main_window/commit_flows.py` — new mixin with the clipboard handler.
- **Modify:** `git_gui/presentation/main_window/main_window.py` — register the new mixin and call its wire method.
- **Create:** `tests/presentation/widgets/test_commit_detail.py` — Feature 1 tests.
- **Modify:** `tests/presentation/widgets/test_graph_context_menu.py` — Feature 2 tests appended.

Files **not** changed: `infrastructure/`, `domain/`, `application/`, `presentation/bus.py`. The underlying `delete_remote_branch` command and bus wiring are already in place.

---

## Task 1: Click commit hash to copy

TDD-flavored. Write the widget tests first, see them fail, implement the widget side, see them pass, then wire DiffWidget forwarding and the MainWindow mixin.

**Files:**
- Create: `tests/presentation/widgets/test_commit_detail.py`
- Modify: `git_gui/presentation/widgets/commit_detail.py`
- Modify: `git_gui/presentation/widgets/diff.py`
- Create: `git_gui/presentation/main_window/commit_flows.py`
- Modify: `git_gui/presentation/main_window/main_window.py`

- [ ] **Step 1: Write the failing widget tests**

Create `tests/presentation/widgets/test_commit_detail.py`:

```python
"""Tests for CommitDetailWidget — click-to-copy commit hash."""
from __future__ import annotations

from datetime import datetime

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from git_gui.domain.entities import Commit
from git_gui.presentation.widgets.commit_detail import CommitDetailWidget


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _make_commit() -> Commit:
    return Commit(
        oid="a" * 40,
        message="msg",
        author="Alice <a@example.com>",
        timestamp=datetime(2026, 5, 6, 12, 0),
        parents=["b" * 40],
    )


def test_oid_rect_is_none_before_set_commit(app, qtbot):
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)
    assert widget._oid_rect is None


def test_clicking_oid_emits_copy_signal_with_full_oid(app, qtbot):
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 120)
    widget.show()
    qtbot.waitExposed(widget)

    commit = _make_commit()
    widget.set_commit(commit, [])
    # Force a paint pass so _oid_rect is populated.
    widget.repaint()
    qtbot.wait(20)

    assert widget._oid_rect is not None

    with qtbot.waitSignal(widget.commit_oid_copy_requested, timeout=500) as blocker:
        center = widget._oid_rect.center()
        qtbot.mouseClick(widget, Qt.LeftButton, pos=center)

    assert blocker.args == [commit.oid]


def test_clicking_outside_oid_does_not_emit(app, qtbot):
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 120)
    widget.show()
    qtbot.waitExposed(widget)

    commit = _make_commit()
    widget.set_commit(commit, [])
    widget.repaint()
    qtbot.wait(20)

    received = []
    widget.commit_oid_copy_requested.connect(lambda oid: received.append(oid))

    # Click in the bottom-right corner — well outside the OID rect.
    qtbot.mouseClick(widget, Qt.LeftButton, pos=widget.rect().bottomRight() - widget.rect().topLeft() + widget.rect().topLeft())  # use widget.rect().bottomRight() directly below
    # Use a position guaranteed to be outside _oid_rect:
    far = widget.rect().bottomRight()
    qtbot.mouseClick(widget, Qt.LeftButton, pos=far)

    assert received == []


def test_clear_resets_oid_rect(app, qtbot):
    widget = CommitDetailWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 120)
    widget.show()
    qtbot.waitExposed(widget)

    widget.set_commit(_make_commit(), [])
    widget.repaint()
    qtbot.wait(20)
    assert widget._oid_rect is not None

    widget.clear()
    assert widget._oid_rect is None
```

- [ ] **Step 2: Run the tests and confirm they FAIL**

Run: `rtk uv run pytest tests/presentation/widgets/test_commit_detail.py -v`

Expected: 4 tests collected, all FAIL. Most likely failure modes: `AttributeError: 'CommitDetailWidget' object has no attribute '_oid_rect'`, `AttributeError: ... has no attribute 'commit_oid_copy_requested'`, or similar — confirms the widget doesn't yet have the new machinery.

- [ ] **Step 3: Modify `CommitDetailWidget` — add signal, rect, and mouse handlers**

Open `git_gui/presentation/widgets/commit_detail.py`. The current file imports and class definition look like:

```python
from __future__ import annotations
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QWidget
```

Update the imports to also pull `Signal` and `QFont`:

```python
from __future__ import annotations
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget
```

In the `CommitDetailWidget` class body (just before `__init__`), add the signal:

```python
class CommitDetailWidget(QWidget):
    commit_oid_copy_requested = Signal(str)  # full 40-char OID

    def __init__(self, parent=None) -> None:
        ...
```

In `__init__`, after the existing `self._refs: list[str] = []` line, add `_oid_rect` initialization and enable mouse tracking:

```python
        self._oid_rect: QRect | None = None
        self.setMouseTracking(True)
```

Update `clear()` to reset `_oid_rect`:

```python
    def clear(self) -> None:
        self._commit = None
        self._refs = []
        self._avatar_hash = None
        self._oid_rect = None
        self.update()
```

In `paintEvent`, find the line that draws the OID:

```python
        painter.setPen(on_surface)
        painter.drawText(x, y + fm.ascent(), c.oid)
        x += fm.horizontalAdvance(c.oid) + BADGE_GAP * 2
```

Replace with the underlined-font version that also tracks the rect:

```python
        oid_font = QFont(painter.font())
        oid_font.setUnderline(True)
        painter.setFont(oid_font)
        painter.setPen(on_surface)
        painter.drawText(x, y + fm.ascent(), c.oid)
        oid_w = fm.horizontalAdvance(c.oid)
        self._oid_rect = QRect(x, y, oid_w, line_h)
        # Restore the default font for whatever follows on this line.
        oid_font.setUnderline(False)
        painter.setFont(oid_font)
        x += oid_w + BADGE_GAP * 2
```

At the end of the class, add the mouse handlers:

```python
    def mouseMoveEvent(self, event) -> None:
        if self._oid_rect is not None and self._oid_rect.contains(event.pos()):
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if (event.button() == Qt.LeftButton
                and self._oid_rect is not None
                and self._oid_rect.contains(event.pos())
                and self._commit is not None):
            self.commit_oid_copy_requested.emit(self._commit.oid)
            event.accept()
            return
        super().mousePressEvent(event)
```

- [ ] **Step 4: Run the widget tests and confirm PASS**

Run: `rtk uv run pytest tests/presentation/widgets/test_commit_detail.py -v`

Expected: 4 PASSED. If any test still fails:
- Rect not populated → confirm `widget.repaint()` is called and `qtbot.wait(20)` is enough.
- Click test misses the rect → check `_oid_rect.center()` is inside the visible widget area (widget is 800×120, OID line is row 2, should be well within view).

- [ ] **Step 5: Forward the signal through `DiffWidget`**

Open `git_gui/presentation/widgets/diff.py`. Find the existing class-level signals (around line 142, where `submodule_open_requested` is declared):

```python
    submodule_open_requested = Signal(str)  # emits the submodule path (relative)
```

Add immediately after:

```python
    commit_oid_copy_requested = Signal(str)  # full 40-char OID — forwarded from _detail
```

Then in `__init__`, after `self._detail` is constructed (where the existing signal connections live), add:

```python
        self._detail.commit_oid_copy_requested.connect(
            self.commit_oid_copy_requested.emit
        )
```

Place this near the other `self._detail.*` connections to keep the wiring co-located.

- [ ] **Step 6: Create the new `CommitFlowsMixin`**

Create `git_gui/presentation/main_window/commit_flows.py`:

```python
# git_gui/presentation/main_window/commit_flows.py
from __future__ import annotations

from PySide6.QtGui import QGuiApplication


class CommitFlowsMixin:
    """Commit-context UX flows (clipboard copy, etc.).

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__ (`self._diff`,
    `self.statusBar()`).
    """

    def _wire_commit_flow_signals(self) -> None:
        self._diff.commit_oid_copy_requested.connect(
            self._on_commit_oid_copy_requested
        )

    def _on_commit_oid_copy_requested(self, oid: str) -> None:
        QGuiApplication.clipboard().setText(oid)
        self.statusBar().showMessage(f"Copied {oid[:7]}", 2000)
```

- [ ] **Step 7: Register `CommitFlowsMixin` in `MainWindow`**

Open `git_gui/presentation/main_window/main_window.py`. Around line 20-29, the file imports each existing flow mixin:

```python
from git_gui.presentation.main_window.branch_flows import BranchFlowsMixin
from git_gui.presentation.main_window.cherry_pick_revert_flows import CherryPickRevertFlowsMixin
from git_gui.presentation.main_window.merge_rebase_flows import MergeRebaseFlowsMixin
...
from git_gui.presentation.main_window.stash_flows import StashFlowsMixin
from git_gui.presentation.main_window.tag_flows import TagFlowsMixin
```

Add the import:

```python
from git_gui.presentation.main_window.commit_flows import CommitFlowsMixin
```

In the class declaration (line 32):

```python
class MainWindow(QMainWindow, ReloadCoordinatorMixin, RightPanelMixin, ResetFlowMixin, StashFlowsMixin, BranchFlowsMixin, CherryPickRevertFlowsMixin, TagFlowsMixin, MergeRebaseFlowsMixin, RemoteOpQueueMixin, RepoLifecycleMixin):
```

Add `CommitFlowsMixin` to the base list. Place it near the other domain flows for readability:

```python
class MainWindow(QMainWindow, ReloadCoordinatorMixin, RightPanelMixin, ResetFlowMixin, StashFlowsMixin, BranchFlowsMixin, CherryPickRevertFlowsMixin, TagFlowsMixin, MergeRebaseFlowsMixin, CommitFlowsMixin, RemoteOpQueueMixin, RepoLifecycleMixin):
```

In `__init__` (around line 49-58), the existing code calls each `_wire_*` method:

```python
        self._wire_reload_signals()
        self._wire_right_panel_signals()
        self._wire_reset_flow_signals()
        self._wire_stash_flow_signals()
        self._wire_branch_flow_signals()
        self._wire_cherry_pick_revert_flow_signals()
        self._wire_tag_flow_signals()
        self._wire_merge_rebase_flow_signals()
        self._wire_remote_op_signals()
        self._wire_repo_lifecycle_signals()
```

Add the new wire call alongside, immediately after `_wire_merge_rebase_flow_signals()`:

```python
        self._wire_merge_rebase_flow_signals()
        self._wire_commit_flow_signals()
        self._wire_remote_op_signals()
```

- [ ] **Step 8: Run the full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED. The new tests in `test_commit_detail.py` pass; nothing else regressed because the widget's existing public surface (`set_commit`, `clear`, paint output) is unchanged — only mouse event handling and an additional signal were added.

- [ ] **Step 9: Commit**

```bash
rtk git add tests/presentation/widgets/test_commit_detail.py git_gui/presentation/widgets/commit_detail.py git_gui/presentation/widgets/diff.py git_gui/presentation/main_window/commit_flows.py git_gui/presentation/main_window/main_window.py
rtk git commit -m "$(cat <<'EOF'
feat(commit-detail): copy commit hash on click

Hit-test the OID rect during paint and emit
commit_oid_copy_requested when the user left-clicks the hash. The
hash is now drawn with an underlined font and the cursor turns into
a pointing hand on hover. DiffWidget forwards the signal to
MainWindow's new CommitFlowsMixin, which writes the full 40-char
OID to the clipboard and flashes a "Copied <short_oid>" message in
the status bar for 2 seconds.

Adds tests covering the empty-state rect, click-emits-signal,
click-outside-no-emit, and clear-resets-rect cases.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Graph context menu deletes remote branch

TDD again: write tests for the new `_emit_remote_delete` helper first, see them fail, implement helper + signal + menu entries, see tests pass, then wire to the existing handler.

**Files:**
- Modify: `tests/presentation/widgets/test_graph_context_menu.py`
- Modify: `git_gui/presentation/widgets/graph.py`
- Modify: `git_gui/presentation/main_window/branch_flows.py`

- [ ] **Step 1: Write the failing helper tests**

Append to `tests/presentation/widgets/test_graph_context_menu.py`:

```python
# ── Remote branch delete from context menu ─────────────────────────────


def test_emit_remote_delete_splits_remote_and_branch(qtbot):
    """`_emit_remote_delete` should split the qualified name on the first
    slash and emit (remote, branch)."""
    from git_gui.presentation.widgets.graph import GraphWidget
    w = GraphWidget.__new__(GraphWidget)
    from PySide6.QtWidgets import QWidget
    QWidget.__init__(w)
    qtbot.addWidget(w)

    received: list[tuple[str, str]] = []
    w.remote_branch_delete_requested.connect(
        lambda r, b: received.append((r, b))
    )

    w._emit_remote_delete("origin/main")

    assert received == [("origin", "main")]


def test_emit_remote_delete_handles_slash_in_branch_name(qtbot):
    """Branch names can contain slashes (e.g. 'feature/foo'). The split
    must take the first slash only."""
    from git_gui.presentation.widgets.graph import GraphWidget
    w = GraphWidget.__new__(GraphWidget)
    from PySide6.QtWidgets import QWidget
    QWidget.__init__(w)
    qtbot.addWidget(w)

    received: list[tuple[str, str]] = []
    w.remote_branch_delete_requested.connect(
        lambda r, b: received.append((r, b))
    )

    w._emit_remote_delete("origin/feature/foo")

    assert received == [("origin", "feature/foo")]


def test_emit_remote_delete_bails_on_malformed_name(qtbot):
    """A name with no slash means the input is malformed; no signal."""
    from git_gui.presentation.widgets.graph import GraphWidget
    w = GraphWidget.__new__(GraphWidget)
    from PySide6.QtWidgets import QWidget
    QWidget.__init__(w)
    qtbot.addWidget(w)

    received: list[tuple[str, str]] = []
    w.remote_branch_delete_requested.connect(
        lambda r, b: received.append((r, b))
    )

    w._emit_remote_delete("no-slash")

    assert received == []


def test_emit_remote_delete_bails_on_empty_remote(qtbot):
    """A leading slash means empty remote — bail."""
    from git_gui.presentation.widgets.graph import GraphWidget
    w = GraphWidget.__new__(GraphWidget)
    from PySide6.QtWidgets import QWidget
    QWidget.__init__(w)
    qtbot.addWidget(w)

    received: list[tuple[str, str]] = []
    w.remote_branch_delete_requested.connect(
        lambda r, b: received.append((r, b))
    )

    w._emit_remote_delete("/main")

    assert received == []
```

- [ ] **Step 2: Run the new tests and confirm they FAIL**

Run: `rtk uv run pytest tests/presentation/widgets/test_graph_context_menu.py -v -k "emit_remote_delete"`

Expected: 4 tests collected, all FAIL with `AttributeError: 'GraphWidget' object has no attribute 'remote_branch_delete_requested'` (or the helper method).

- [ ] **Step 3: Add the signal and helper to `GraphWidget`**

Open `git_gui/presentation/widgets/graph.py`. Find the existing class-level signals (search for `delete_branch_requested`):

```python
    delete_branch_requested = Signal(str)
```

Add immediately after:

```python
    remote_branch_delete_requested = Signal(str, str)  # (remote, branch)
```

Add the helper method as a private method on `GraphWidget`. Place it near the other context-menu helpers (e.g., right after `_show_context_menu` or `_add_merge_rebase_section`):

```python
    def _emit_remote_delete(self, name: str) -> None:
        """Split a qualified remote-branch name (e.g. 'origin/feature/foo')
        on the first slash and emit (remote, branch). Defensively bail if
        the input is malformed."""
        if "/" not in name:
            return
        remote, branch = name.split("/", 1)
        if not remote or not branch:
            return
        self.remote_branch_delete_requested.emit(remote, branch)
```

- [ ] **Step 4: Run the helper tests and confirm PASS**

Run: `rtk uv run pytest tests/presentation/widgets/test_graph_context_menu.py -v -k "emit_remote_delete"`

Expected: 4 PASSED.

- [ ] **Step 5: Add the "Delete remote branch" menu entries**

Find `_show_context_menu` in `graph.py` (around line 580). The existing local-branch block (around line 628-637) reads:

```python
        if local_branches:
            if len(local_branches) == 1:
                name = local_branches[0]
                menu.addAction(f"Delete branch: {name}").triggered.connect(
                    lambda: self.delete_branch_requested.emit(name))
            else:
                sub = menu.addMenu("Delete branch")
                for name in local_branches:
                    sub.addAction(name).triggered.connect(
                        lambda _checked=False, n=name: self.delete_branch_requested.emit(n))
```

Immediately after this block, add the analogous remote block. First compute the remote-only set; this comes from `real_branches` minus `local_set` (the same `local_set` already computed earlier in the method):

```python
        remote_branches = [n for n in real_branches if n not in local_set]
        if remote_branches:
            if len(remote_branches) == 1:
                name = remote_branches[0]
                menu.addAction(f"Delete remote branch: {name}").triggered.connect(
                    lambda: self._emit_remote_delete(name))
            else:
                sub = menu.addMenu("Delete remote branch")
                for name in remote_branches:
                    sub.addAction(name).triggered.connect(
                        lambda _checked=False, n=name: self._emit_remote_delete(n))
```

- [ ] **Step 6: Wire the new signal in `branch_flows.py`**

Open `git_gui/presentation/main_window/branch_flows.py`. Find `_wire_branch_flow_signals` (line 13):

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

Add one line (place it next to the sidebar's `remote_branch_delete_requested` connection so both routes to the same handler are visible together):

```python
    def _wire_branch_flow_signals(self) -> None:
        self._sidebar.branch_checkout_requested.connect(self._on_branch_changed)
        self._sidebar.branch_delete_requested.connect(self._on_delete_branch)
        self._sidebar.remote_branch_delete_requested.connect(self._on_delete_remote_branch)
        self._graph.remote_branch_delete_requested.connect(self._on_delete_remote_branch)
        self._graph.delete_branch_requested.connect(self._on_delete_branch)
        self._graph.create_branch_requested.connect(self._on_create_branch)
        self._graph.checkout_commit_requested.connect(self._on_checkout_commit)
        self._graph.checkout_branch_requested.connect(self._on_checkout_branch)
```

- [ ] **Step 7: Run the full graph context-menu test file**

Run: `rtk uv run pytest tests/presentation/widgets/test_graph_context_menu.py -v`

Expected: all PASSED — the four new helper tests, plus any pre-existing tests still pass.

- [ ] **Step 8: Run the full suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED.

- [ ] **Step 9: Commit**

```bash
rtk git add tests/presentation/widgets/test_graph_context_menu.py git_gui/presentation/widgets/graph.py git_gui/presentation/main_window/branch_flows.py
rtk git commit -m "$(cat <<'EOF'
feat(graph): delete remote branch from context menu

Mirror the existing local-branch delete pattern in
GraphWidget._show_context_menu so right-clicking a row that carries
a remote ref offers "Delete remote branch: <remote>/<branch>".
Single-entry vs submenu handling matches the local case. The new
remote_branch_delete_requested signal routes to the existing
_on_delete_remote_branch handler in branch_flows, inheriting its
confirmation dialog and remote-op queue handling.

The _emit_remote_delete helper splits the qualified name on the
first slash so branch names containing slashes (e.g.
"origin/feature/foo") work correctly. Defensive bail on malformed
names (no slash, empty remote).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Manual verification

No code changes — this is the human-eyeball pass that automated tests can't substitute for.

**Files:** none modified.

- [ ] **Step 1: Launch the app**

Run: `rtk uv run python main.py`

- [ ] **Step 2: Verify Feature 1 (commit hash copy)**

1. Open a repo and click any commit in the graph.
2. The commit detail panel shows "Commit: <full 40-char hash>". The hash is rendered with an **underline**.
3. Hover the hash. The cursor changes to a **pointing hand**. Hover off the hash — cursor returns to arrow.
4. Click the hash. Status bar at the bottom of the window flashes "Copied <short_oid>" for ~2 seconds.
5. Switch to another app (e.g., a terminal or browser) and paste. The full 40-char hash is on the clipboard.
6. Click another commit, verify the new hash copies correctly (not stale).

If the cursor doesn't change or the click does nothing, check that `setMouseTracking(True)` is in `__init__` and that `_oid_rect` is being set during paint.

- [ ] **Step 3: Verify Feature 2 (graph delete remote branch)**

1. With a repo that has at least one remote-only branch (e.g., `origin/some-feature` not yet checked out locally; if you don't have one, run `git fetch origin` to pick one up).
2. In the graph, right-click the commit row carrying that remote branch. The context menu should include "Delete remote branch: origin/some-feature".
3. Click the entry. A confirmation dialog appears: "Delete remote branch `origin/some-feature`? This cannot be undone." Click **Cancel** — nothing changes; the branch is still in the sidebar.
4. Right-click the same row again, click delete, click **Yes**. Status bar shows the running op; on success, the remote branch disappears from the sidebar and the graph badge for it goes away.
5. Find a row where both a local branch and its tracking remote share the commit (typically: HEAD plus its `origin/<head>`). Right-click. Both "Delete branch: <local>" and "Delete remote branch: <remote>/<local>" should appear.
6. If a row has multiple remote branches, the menu should show a "Delete remote branch" submenu with each branch as a child item.

- [ ] **Step 4: No commit needed**

Manual verification doesn't produce changes. If a real visual or behavioral issue surfaces, surface it before opening the PR.

---

## Self-Review

**Spec coverage:**

Feature 1:
- New `commit_oid_copy_requested` signal on CommitDetailWidget → Step 3. ✅
- `_oid_rect` tracked during paint → Step 3. ✅
- Underlined-font hash → Step 3. ✅
- `setMouseTracking(True)` + `mouseMoveEvent` cursor change → Step 3. ✅
- `mousePressEvent` hit-test → Step 3. ✅
- `leaveEvent` cursor reset → Step 3. ✅
- `clear()` resets the rect → Step 3. ✅
- DiffWidget forwarding → Step 5. ✅
- New `CommitFlowsMixin` with clipboard + status bar → Step 6. ✅
- MainWindow registration → Step 7. ✅
- Tests for empty-state, click-emits, click-outside-no-emit, clear-resets → Step 1. ✅

Feature 2:
- New `remote_branch_delete_requested` signal on GraphWidget → Step 3. ✅
- `_emit_remote_delete` helper with defensive splitting → Step 3. ✅
- Menu entries (single + submenu cases) → Step 5. ✅
- Wire to existing `_on_delete_remote_branch` handler → Step 6. ✅
- Tests for split, slash-in-branch-name, malformed-name, empty-remote → Step 1. ✅

Out of scope per spec:
- Parent OID hashes — explicitly deferred. ✅
- New domain port / command — none needed; existing `delete_remote_branch` is reused. ✅

**Placeholder scan:** none. Every step has full code or exact commands.

**Type/method consistency:**
- Signal names match between widget and forwarder: `commit_oid_copy_requested` (Feature 1), `remote_branch_delete_requested` (Feature 2). ✅
- `_oid_rect` is a `QRect | None`, consistent across init, paint, clear, and event handlers. ✅
- `_emit_remote_delete` signature `(self, name: str) -> None` consistent across helper definition, menu wiring, and tests. ✅
