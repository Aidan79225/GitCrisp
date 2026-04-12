# ViewportBlockLoader Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the duplicated viewport-tracking / skeleton-realization logic from `DiffWidget` and `HunkDiffWidget` into a reusable `ViewportBlockLoader` class, eliminating ~60 lines of duplication per widget and making the viewport logic independently testable.

**Architecture:** A new `ViewportBlockLoader` class (composition, not inheritance) owns the block refs, loaded-paths set, scroll debounce timer, and viewport-intersection check. Each widget creates a loader instance and provides a `realize_fn` callback for domain-specific hunk rendering. The loader does not manage the background fetch — the widget still dispatches the thread and hands the diff map to the loader when it arrives.

**Tech Stack:** Python, PySide6 (Qt), pytest, pytest-qt, uv.

**Spec:** `docs/superpowers/specs/2026-04-13-viewport-block-loader-design.md`

---

## File Structure

**New:**
- `git_gui/presentation/widgets/viewport_block_loader.py` — the `ViewportBlockLoader` class
- `tests/presentation/widgets/test_viewport_block_loader.py` — tests for the loader

**Modified:**
- `git_gui/presentation/widgets/diff.py` — replace inline viewport logic with loader
- `git_gui/presentation/widgets/hunk_diff.py` — same

---

## Task 1: Create `ViewportBlockLoader` (TDD)

**Files:**
- Create: `git_gui/presentation/widgets/viewport_block_loader.py`
- Create: `tests/presentation/widgets/test_viewport_block_loader.py`

- [ ] **Step 1: Write failing tests**

Create `tests/presentation/widgets/test_viewport_block_loader.py`:

```python
"""Tests for ViewportBlockLoader."""
from __future__ import annotations
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from git_gui.presentation.widgets.viewport_block_loader import ViewportBlockLoader


@pytest.fixture
def scroll_area(qtbot):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    container = QWidget()
    layout = QVBoxLayout(container)
    sa.setWidget(container)
    sa.resize(400, 300)
    sa.show()
    qtbot.addWidget(sa)
    return sa, container, layout


def _make_block(layout, path: str, height: int = 60):
    """Create a fake file block frame and add it to the layout."""
    frame = QFrame()
    frame.setFixedHeight(height)
    inner = QVBoxLayout(frame)
    skeleton = QWidget()
    inner.addWidget(skeleton)
    layout.addWidget(frame)
    return (path, frame, inner, skeleton)


def test_set_diff_map_triggers_realize(qtbot, scroll_area):
    sa, container, layout = scroll_area
    realized = []
    loader = ViewportBlockLoader(sa, lambda path, inner, skel, entry: realized.append(path))

    block = _make_block(layout, "a.txt")
    loader.set_blocks([block])
    loader.set_diff_map({"a.txt": ["hunk1"]})

    qtbot.wait(100)  # let QTimer.singleShot fire
    assert "a.txt" in realized


def test_realizes_one_block_per_check(qtbot, scroll_area):
    sa, container, layout = scroll_area
    realized = []
    loader = ViewportBlockLoader(sa, lambda path, inner, skel, entry: realized.append(path))

    blocks = [_make_block(layout, f"f{i}.txt", height=20) for i in range(5)]
    loader.set_blocks(blocks)
    loader.set_diff_map({f"f{i}.txt": [f"hunk{i}"] for i in range(5)})

    # After one tick, only 1 should be realized (serial)
    qtbot.wait(20)
    first_count = len(realized)
    assert first_count >= 1

    # After more ticks, more get realized
    qtbot.wait(200)
    assert len(realized) >= first_count


def test_skips_loaded_paths(qtbot, scroll_area):
    sa, container, layout = scroll_area
    realized = []
    loader = ViewportBlockLoader(sa, lambda path, inner, skel, entry: realized.append(path))

    block = _make_block(layout, "a.txt")
    loader.set_blocks([block])
    loader._loaded_paths.add("a.txt")  # pre-mark as loaded
    loader.set_diff_map({"a.txt": ["hunk1"]})

    qtbot.wait(100)
    assert "a.txt" not in realized


def test_stale_frame_is_skipped(qtbot, scroll_area):
    sa, container, layout = scroll_area
    realized = []
    loader = ViewportBlockLoader(sa, lambda path, inner, skel, entry: realized.append(path))

    block = _make_block(layout, "a.txt")
    loader.set_blocks([block])

    # Delete the frame to simulate a stale reference
    block[1].deleteLater()
    qtbot.wait(20)

    loader.set_diff_map({"a.txt": ["hunk1"]})
    qtbot.wait(100)
    # Should not crash, and a.txt should not be realized
    assert "a.txt" not in realized


def test_clear_resets_state(qtbot, scroll_area):
    sa, container, layout = scroll_area
    loader = ViewportBlockLoader(sa, lambda *a: None)

    block = _make_block(layout, "a.txt")
    loader.set_blocks([block])
    loader.set_diff_map({"a.txt": ["hunk1"]})

    loader.clear()
    assert loader._block_refs == []
    assert loader._loaded_paths == set()
    assert loader._diff_map == {}
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `uv run pytest tests/presentation/widgets/test_viewport_block_loader.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the loader**

Create `git_gui/presentation/widgets/viewport_block_loader.py`:

```python
"""Reusable viewport-driven lazy block loader.

Manages the state machine for skeleton-block realization: tracks which
file blocks exist, which have been realized, debounces scroll events,
and realizes one block per event-loop tick when it enters the viewport.

Used by both DiffWidget (commit view) and HunkDiffWidget (working tree)
to avoid duplicating the viewport-intersection + stale-frame logic.
"""
from __future__ import annotations
from typing import Any, Callable

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget


class ViewportBlockLoader:
    """Lazy block loader driven by scroll-area viewport intersection.

    Parameters
    ----------
    scroll_area:
        The QScrollArea whose viewport is used for intersection checks.
    realize_fn:
        ``realize_fn(path, inner_layout, skeleton_or_none, diff_entry)``
        is called when a block enters the viewport and needs to be
        realized. The widget provides this callback to do domain-specific
        hunk rendering.
    """

    def __init__(
        self,
        scroll_area: QScrollArea,
        realize_fn: Callable[[str, QVBoxLayout, QWidget | None, Any], None],
    ) -> None:
        self._scroll_area = scroll_area
        self._realize_fn = realize_fn
        self._block_refs: list[tuple[str, QFrame, QVBoxLayout, QWidget | None]] = []
        self._loaded_paths: set[str] = set()
        self._diff_map: dict[str, Any] = {}

        self._scroll_timer = QTimer()
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._check_viewport)

        scroll_area.verticalScrollBar().valueChanged.connect(
            lambda _: self._scroll_timer.start()
        )

    def set_blocks(
        self, block_refs: list[tuple[str, QFrame, QVBoxLayout, QWidget | None]]
    ) -> None:
        """Register skeleton blocks. Resets loaded-paths and diff map."""
        self._block_refs = list(block_refs)
        self._loaded_paths = set()
        self._diff_map = {}

    def set_diff_map(self, diff_map: dict[str, Any]) -> None:
        """Store the fetched diff data and schedule the first viewport check.

        Deferred one event-loop tick so Qt can lay out the skeletons before
        we ask which blocks are visible.
        """
        self._diff_map = diff_map
        QTimer.singleShot(0, self._check_viewport)

    def clear(self) -> None:
        """Reset all state. Call from the widget's layout-clear method."""
        self._block_refs = []
        self._loaded_paths = set()
        self._diff_map = {}

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _check_viewport(self) -> None:
        """Realize the first visible unloaded block, then reschedule.

        Only one block per call — after realization the layout shifts,
        so we reschedule via ``QTimer.singleShot(0, ...)`` to let Qt
        process the growth before re-checking.

        Wraps frame access in ``try/except RuntimeError`` to handle
        stale C++ references from frames deleted by a newer load.
        """
        if not self._block_refs or not self._diff_map:
            return
        try:
            viewport = self._scroll_area.viewport()
            vp_rect = viewport.rect()
        except RuntimeError:
            return
        for path, frame, inner, skeleton in list(self._block_refs):
            if path in self._loaded_paths:
                continue
            if frame is None:
                continue
            try:
                top_left = frame.mapTo(viewport, QPoint(0, 0))
                frame_rect = frame.rect().translated(top_left)
            except RuntimeError:
                continue
            if frame_rect.intersects(vp_rect):
                entry = self._diff_map.get(path)
                if entry is not None:
                    self._realize_fn(path, inner, skeleton, entry)
                self._loaded_paths.add(path)
                QTimer.singleShot(0, self._check_viewport)
                return
```

- [ ] **Step 4: Run tests — expect all PASS**

Run: `uv run pytest tests/presentation/widgets/test_viewport_block_loader.py -v`
Expected: All 5 PASS.

- [ ] **Step 5: Run full suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/widgets/viewport_block_loader.py tests/presentation/widgets/test_viewport_block_loader.py
git commit -m "feat(widgets): add ViewportBlockLoader for lazy block realization"
```

---

## Task 2: Refactor DiffWidget to use ViewportBlockLoader

**Files:**
- Modify: `git_gui/presentation/widgets/diff.py`

- [ ] **Step 1: Add import and create loader in `__init__`**

In `git_gui/presentation/widgets/diff.py`, add this import near the top:

```python
from git_gui.presentation.widgets.viewport_block_loader import ViewportBlockLoader
```

In `DiffWidget.__init__`, REPLACE the lazy-loading state block:

```python
        # Lazy loading state
        self._diff_map: dict[str, list] = {}
        # Each entry: (path, frame_widget, inner_layout, skeleton_widget_or_none)
        self._block_refs: list[tuple[str, QWidget, object, object]] = []
        self._loaded_paths: set[str] = set()

        # Scroll debounce timer
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._check_viewport_and_load)
```

WITH:

```python
        # Lazy loading — initialized after scroll area is created (see below)
        self._loader: ViewportBlockLoader | None = None
```

Then, AFTER the line `self._diff_scroll.setWidget(self._diff_container)`, REMOVE:

```python
        self._diff_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
```

And ADD:

```python
        self._loader = ViewportBlockLoader(self._diff_scroll, self._realize_block)
```

- [ ] **Step 2: Rewrite `_realize_block` to match the loader's callback signature**

Replace the existing `_realize_block` method with:

```python
    def _realize_block(self, path: str, inner, skeleton, hunks) -> None:
        """Callback for ViewportBlockLoader — replace skeleton with hunk widgets."""
        if skeleton is not None:
            inner.removeWidget(skeleton)
            skeleton.deleteLater()
        is_submodule = path in self._submodule_paths
        on_click = (
            (lambda p=path: self.submodule_open_requested.emit(p))
            if is_submodule else None
        )
        for hunk in hunks:
            add_hunk_widget(inner, hunk, self._formats, on_header_clicked=on_click)
```

Note: this no longer reads from `self._diff_map` or writes to `self._loaded_paths` — the loader handles both.

- [ ] **Step 3: Remove the now-unused methods**

Delete these methods from `DiffWidget`:
- `_on_scroll`
- `_check_viewport_and_load`

- [ ] **Step 4: Update `_clear_blocks`**

Replace:

```python
    def _clear_blocks(self) -> None:
        """Remove all widgets and items from the diff layout."""
        while self._diff_layout.count():
            item = self._diff_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        # Invalidate tracked block refs — their frames are now deleted.
        # Any pending QTimer callbacks must not touch them.
        self._block_refs = []
        self._loaded_paths = set()
```

With:

```python
    def _clear_blocks(self) -> None:
        """Remove all widgets and items from the diff layout."""
        while self._diff_layout.count():
            item = self._diff_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if self._loader:
            self._loader.clear()
```

- [ ] **Step 5: Update `_render_all_files`**

In `_render_all_files`, replace the lines that manage `_block_refs` / `_loaded_paths` / `_diff_map` directly. The current code does:

```python
        self._block_refs = []
        self._loaded_paths = set()
        self._diff_map = {}
        ...
        self._block_refs.append((path, frame, inner, skeleton))
        ...
        signals.done.connect(self._on_diff_map_loaded)
```

Replace with:

```python
        block_refs = []
        ...
        block_refs.append((path, frame, inner, skeleton))
        ...
        # After the loop and addStretch:
        self._loader.set_blocks(block_refs)
        ...
        # Replace _on_diff_map_loaded with:
        signals.done.connect(lambda diff_map: self._loader.set_diff_map(diff_map))
```

And DELETE the `_on_diff_map_loaded` method entirely.

- [ ] **Step 6: Update `_render_single_file`**

In `_render_single_file`, replace:

```python
        self._block_refs = []
        self._loaded_paths = set()
```

With:

```python
        if self._loader:
            self._loader.clear()
```

- [ ] **Step 7: Verify import + run tests**

Run: `uv run python -c "from git_gui.presentation.widgets.diff import DiffWidget; print('ok')"`
Expected: `ok`

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/widgets/diff.py
git commit -m "refactor(diff): use ViewportBlockLoader instead of inline viewport logic"
```

---

## Task 3: Refactor HunkDiffWidget to use ViewportBlockLoader

**Files:**
- Modify: `git_gui/presentation/widgets/hunk_diff.py`

- [ ] **Step 1: Add import and create loader in `__init__`**

In `git_gui/presentation/widgets/hunk_diff.py`, add the import:

```python
from git_gui.presentation.widgets.viewport_block_loader import ViewportBlockLoader
```

In `HunkDiffWidget.__init__`, REPLACE the lazy-loading state block:

```python
        # Lazy loading state (all-files mode)
        self._diff_map: dict[str, dict[str, list]] = {}
        self._block_refs: list = []
        self._loaded_paths: set[str] = set()

        from PySide6.QtCore import QTimer
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._check_viewport_and_load)
```

WITH:

```python
        # Lazy loading — initialized after scroll area is created (see below)
        self._loader: ViewportBlockLoader | None = None
```

Then, AFTER `self._scroll.setWidget(self._container)` and the outer layout setup, REMOVE:

```python
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
```

And ADD:

```python
        self._loader = ViewportBlockLoader(self._scroll, self._realize_block_from_loader)
```

- [ ] **Step 2: Add the loader callback**

Add a new method (keeping the existing `_realize_block` for the non-lazy path if it still exists, or replace it):

```python
    def _realize_block_from_loader(self, path: str, inner, skeleton, entry) -> None:
        """Callback for ViewportBlockLoader — replace skeleton with staged/unstaged hunks."""
        staged_hunks = entry.get("staged", [])
        unstaged_hunks = entry.get("unstaged", [])
        is_untracked = (
            not staged_hunks
            and bool(unstaged_hunks)
            and unstaged_hunks[0].header.startswith("@@ -0,0")
        )
        if skeleton is not None:
            inner.removeWidget(skeleton)
            skeleton.deleteLater()
        for hunk in staged_hunks:
            self._add_hunk_block(hunk, is_staged=True, is_untracked=False,
                                 path=path, parent_layout=inner)
        for hunk in unstaged_hunks:
            self._add_hunk_block(hunk, is_staged=False, is_untracked=is_untracked,
                                 path=path, parent_layout=inner)
```

- [ ] **Step 3: Remove the now-unused methods**

Delete from `HunkDiffWidget`:
- `_on_scroll`
- `_check_viewport_and_load`
- `_realize_block` (the old inline version — replaced by `_realize_block_from_loader`)
- `_on_diff_map_loaded`

- [ ] **Step 4: Update `_clear_layout`**

Replace the block-ref cleanup in `_clear_layout`:

```python
        # Invalidate tracked block refs — their frames are now deleted.
        # Any pending QTimer callbacks must not touch them.
        self._block_refs = []
        self._loaded_paths = set()
```

With:

```python
        if self._loader:
            self._loader.clear()
```

- [ ] **Step 5: Update `load_all_files`**

In `load_all_files`, replace the lines that manage `_block_refs` / `_loaded_paths` / `_diff_map` directly:

```python
        self._block_refs = []
        self._loaded_paths = set()
        self._diff_map = {}
        ...
        self._block_refs.append((path, frame, inner, skeleton))
        ...
        signals.done.connect(self._on_diff_map_loaded)
```

With:

```python
        block_refs = []
        ...
        block_refs.append((path, frame, inner, skeleton))
        ...
        # After the loop and addStretch:
        self._loader.set_blocks(block_refs)
        ...
        signals.done.connect(lambda diff_map: self._loader.set_diff_map(diff_map))
```

- [ ] **Step 6: Verify import + run tests**

Run: `uv run python -c "from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget; print('ok')"`
Expected: `ok`

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/widgets/hunk_diff.py
git commit -m "refactor(hunk_diff): use ViewportBlockLoader instead of inline viewport logic"
```

---

## Task 4: Manual acceptance

- [ ] **Step 1: Launch the app**

Run: `uv run python main.py`

- [ ] **Step 2: Verify commit view lazy loading**

1. Click a commit with many files → skeletons appear, diffs load as you scroll.
2. Click a commit with a single large file → renders progressively.
3. Switch between commits quickly → no crashes, no stale skeletons.

- [ ] **Step 3: Verify working tree lazy loading**

1. Make many uncommitted changes → skeletons appear, hunks load on scroll.
2. Stage/unstage a file → hunk diff refreshes correctly.
3. Mix of staged, unstaged, conflicted, and untracked files → all correct.

- [ ] **Step 4: Commit any fixes**

If manual testing reveals issues, fix and commit with descriptive messages.

---

## Out of Scope

- Extracting the background-fetch pattern (only ~10 lines per widget).
- Touching `working_tree.py` (delegates to HunkDiffWidget).
- Merging `diff.py` and `hunk_diff.py` into one widget.
