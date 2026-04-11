# Lazy Diff Loading — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make commit and working-tree views responsive for commits with many files or large diffs by batching the diff fetch, rendering file blocks as skeletons first, realizing them only when they enter the viewport, and splitting large hunks into chunked rendering across event-loop ticks.

**Architecture:** New reader methods compute all file diffs in one tree-diff call and return a `{path: hunks}` map. Widgets render skeletons immediately, dispatch a background thread to fetch the map, then use a debounced scroll handler to realize file blocks as they become visible. Large hunks render in 100-line batches via `QTimer.singleShot`.

**Tech Stack:** Python, PySide6 (Qt), pygit2, pytest, pytest-qt, uv.

**Spec:** `docs/superpowers/specs/2026-04-11-lazy-diff-loading-design.md`

---

## File Structure

**Modified:**
- `git_gui/domain/ports.py` — add 2 reader methods
- `git_gui/infrastructure/pygit2_repo.py` — implement 2 methods
- `git_gui/application/queries.py` — add 2 queries
- `git_gui/presentation/bus.py` — wire 2 queries
- `git_gui/presentation/widgets/diff_block.py` — chunked hunk rendering
- `git_gui/presentation/widgets/diff.py` — commit view lazy loading
- `git_gui/presentation/widgets/hunk_diff.py` — working tree lazy loading

**Test files modified:**
- `tests/infrastructure/test_reads.py`
- `tests/application/test_queries.py`
- `tests/presentation/test_diff_model.py` or new `tests/presentation/widgets/test_diff_block.py`

---

## Task 1: Add reader methods to ports

**Files:**
- Modify: `git_gui/domain/ports.py`

- [ ] **Step 1: Add method declarations**

In `git_gui/domain/ports.py`, add these lines to the `IRepositoryReader` Protocol body (after `get_file_diff`):

```python
    def get_commit_diff_map(self, oid: str) -> dict[str, list[Hunk]]: ...
    def get_working_tree_diff_map(self) -> dict[str, dict[str, list[Hunk]]]: ...
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from git_gui.domain.ports import IRepositoryReader; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add git_gui/domain/ports.py
git commit -m "feat(domain): add get_commit_diff_map and get_working_tree_diff_map ports"
```

---

## Task 2: Implement get_commit_diff_map (TDD)

**Files:**
- Test: `tests/infrastructure/test_reads.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Write failing tests**

Read the top of `tests/infrastructure/test_reads.py` to find the `repo_impl`/`repo_path` fixture pattern. Append:

```python
def test_get_commit_diff_map_returns_all_files(repo_impl, repo_path):
    """A commit with 3 modified files returns all 3 in the diff map."""
    # Initial commit
    (repo_path / "a.txt").write_text("a1\n")
    (repo_path / "b.txt").write_text("b1\n")
    (repo_path / "c.txt").write_text("c1\n")
    repo_impl.stage(["a.txt", "b.txt", "c.txt"])
    repo_impl.commit("initial")
    # Second commit modifying all three
    (repo_path / "a.txt").write_text("a2\n")
    (repo_path / "b.txt").write_text("b2\n")
    (repo_path / "c.txt").write_text("c2\n")
    repo_impl.stage(["a.txt", "b.txt", "c.txt"])
    second = repo_impl.commit("second")

    result = repo_impl.get_commit_diff_map(second.oid)

    assert set(result.keys()) == {"a.txt", "b.txt", "c.txt"}
    for path in ("a.txt", "b.txt", "c.txt"):
        assert len(result[path]) > 0, f"{path} has no hunks"


def test_get_commit_diff_map_initial_commit(repo_impl, repo_path):
    """Initial commit (no parent) returns all files as additions."""
    (repo_path / "new.txt").write_text("hello\n")
    repo_impl.stage(["new.txt"])
    first = repo_impl.commit("first")

    result = repo_impl.get_commit_diff_map(first.oid)

    assert "new.txt" in result
    assert len(result["new.txt"]) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_reads.py -v -k get_commit_diff_map`
Expected: FAIL with `AttributeError: 'Pygit2Repository' object has no attribute 'get_commit_diff_map'`.

- [ ] **Step 3: Implement**

In `git_gui/infrastructure/pygit2_repo.py`, add this method to `Pygit2Repository` (place it right after the existing `get_file_diff` method):

```python
def get_commit_diff_map(self, oid: str) -> dict[str, list[Hunk]]:
    """Return a dict of {path: [Hunk, ...]} for every changed file in the commit.

    Computes the full tree diff exactly once, instead of the per-file diff pattern.
    """
    commit = self._repo.get(oid)
    if commit.parents:
        diff = self._repo.diff(commit.parents[0].tree, commit.tree)
    else:
        empty_tree_oid = self._repo.TreeBuilder().write()
        empty_tree = self._repo.get(empty_tree_oid)
        diff = self._repo.diff(empty_tree, commit.tree)
    result: dict[str, list[Hunk]] = {}
    for patch in diff:
        path = patch.delta.new_file.path or patch.delta.old_file.path
        if path:
            result[path] = _diff_to_hunks(patch)
    return result
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/infrastructure/test_reads.py -v -k get_commit_diff_map`
Expected: Both PASS.

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_reads.py
git commit -m "feat(infra): implement get_commit_diff_map with single tree diff call"
```

---

## Task 3: Implement get_working_tree_diff_map (TDD)

**Files:**
- Test: `tests/infrastructure/test_reads.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/infrastructure/test_reads.py`:

```python
def test_get_working_tree_diff_map_staged_and_unstaged(repo_impl, repo_path):
    """Staged + unstaged changes appear in the map with correct sub-dict keys."""
    (repo_path / "base.txt").write_text("base\n")
    repo_impl.stage(["base.txt"])
    repo_impl.commit("base")
    # Staged change
    (repo_path / "staged.txt").write_text("staged content\n")
    repo_impl.stage(["staged.txt"])
    # Unstaged change
    (repo_path / "base.txt").write_text("base modified\n")

    result = repo_impl.get_working_tree_diff_map()

    assert "staged.txt" in result
    assert result["staged.txt"]["staged"], "staged.txt should have staged hunks"
    assert "base.txt" in result
    assert result["base.txt"]["unstaged"], "base.txt should have unstaged hunks"


def test_get_working_tree_diff_map_includes_untracked(repo_impl, repo_path):
    """Untracked files appear in the map with unstaged hunks."""
    (repo_path / "base.txt").write_text("base\n")
    repo_impl.stage(["base.txt"])
    repo_impl.commit("base")
    (repo_path / "untracked.txt").write_text("hi\n")

    result = repo_impl.get_working_tree_diff_map()

    assert "untracked.txt" in result
    assert result["untracked.txt"]["unstaged"]


def test_get_working_tree_diff_map_empty_when_clean(repo_impl, repo_path):
    """A clean working tree returns an empty dict."""
    (repo_path / "base.txt").write_text("base\n")
    repo_impl.stage(["base.txt"])
    repo_impl.commit("base")

    result = repo_impl.get_working_tree_diff_map()

    assert result == {}
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/infrastructure/test_reads.py -v -k get_working_tree_diff_map`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement**

In `git_gui/infrastructure/pygit2_repo.py`, add this method to `Pygit2Repository` right after `get_commit_diff_map`:

```python
def get_working_tree_diff_map(self) -> dict[str, dict[str, list[Hunk]]]:
    """Return {path: {"staged": [...], "unstaged": [...]}} for every changed file.

    Computes the full staged diff and unstaged diff exactly once each.
    """
    result: dict[str, dict[str, list[Hunk]]] = {}

    # Staged: index vs HEAD
    try:
        if self._repo.head_is_unborn:
            empty_tree_oid = self._repo.TreeBuilder().write()
            empty_tree = self._repo.get(empty_tree_oid)
            staged_diff = self._repo.index.diff_to_tree(empty_tree)
        else:
            head_commit = self._repo.head.peel(pygit2.Commit)
            staged_diff = self._repo.index.diff_to_tree(head_commit.tree)
        for patch in staged_diff:
            path = patch.delta.new_file.path or patch.delta.old_file.path
            if not path:
                continue
            result.setdefault(path, {"staged": [], "unstaged": []})
            result[path]["staged"] = _diff_to_hunks(patch)
    except Exception:
        pass

    # Unstaged: workdir vs index
    try:
        unstaged_diff = self._repo.diff()
        for patch in unstaged_diff:
            path = patch.delta.new_file.path or patch.delta.old_file.path
            if not path:
                continue
            result.setdefault(path, {"staged": [], "unstaged": []})
            hunks = _diff_to_hunks(patch)
            if not hunks:
                # Conflicted or empty patch — fall through to status-based synthesis
                try:
                    status = self._repo.status_file(path)
                except KeyError:
                    status = 0
                if status & pygit2.GIT_STATUS_CONFLICTED:
                    conflict_hunks = _synthesise_conflict_hunk(self._repo.workdir, path)
                    if conflict_hunks:
                        hunks = conflict_hunks
                    else:
                        hunks = self._diff_workfile_against_head(path)
            result[path]["unstaged"] = hunks
    except Exception:
        pass

    # Untracked files: iterate status and synthesise
    try:
        for path, status in self._repo.status().items():
            if status & pygit2.GIT_STATUS_WT_NEW:
                result.setdefault(path, {"staged": [], "unstaged": []})
                result[path]["unstaged"] = _synthesise_untracked_hunk(self._repo.workdir, path)
    except Exception:
        pass

    return result
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/infrastructure/test_reads.py -v -k get_working_tree_diff_map`
Expected: All 3 PASS.

- [ ] **Step 5: Run full suite to check no regressions**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_reads.py
git commit -m "feat(infra): implement get_working_tree_diff_map"
```

---

## Task 4: Add application queries (TDD)

**Files:**
- Test: `tests/application/test_queries.py`
- Modify: `git_gui/application/queries.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/application/test_queries.py`:

```python
from git_gui.application.queries import GetCommitDiffMap, GetWorkingTreeDiffMap


class _FakeDiffMapReader:
    def get_commit_diff_map(self, oid):
        return {"a.txt": ["hunk1"]}

    def get_working_tree_diff_map(self):
        return {"b.txt": {"staged": ["h1"], "unstaged": []}}


def test_get_commit_diff_map_passthrough():
    q = GetCommitDiffMap(_FakeDiffMapReader())
    assert q.execute("abc123") == {"a.txt": ["hunk1"]}


def test_get_working_tree_diff_map_passthrough():
    q = GetWorkingTreeDiffMap(_FakeDiffMapReader())
    assert q.execute() == {"b.txt": {"staged": ["h1"], "unstaged": []}}
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/application/test_queries.py -v -k "commit_diff_map or working_tree_diff_map"`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

Append to `git_gui/application/queries.py`:

```python
class GetCommitDiffMap:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, oid: str) -> dict[str, list[Hunk]]:
        return self._reader.get_commit_diff_map(oid)


class GetWorkingTreeDiffMap:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> dict[str, dict[str, list[Hunk]]]:
        return self._reader.get_working_tree_diff_map()
```

Make sure `Hunk` is imported from entities at the top of the file. It's likely already imported for existing queries.

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/application/test_queries.py -v -k "commit_diff_map or working_tree_diff_map"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add git_gui/application/queries.py tests/application/test_queries.py
git commit -m "feat(application): add GetCommitDiffMap and GetWorkingTreeDiffMap queries"
```

---

## Task 5: Wire queries into bus

**Files:**
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Update imports**

In `git_gui/presentation/bus.py`, add `GetCommitDiffMap, GetWorkingTreeDiffMap` to the queries import block.

- [ ] **Step 2: Add fields and wiring**

Add `get_commit_diff_map: GetCommitDiffMap` and `get_working_tree_diff_map: GetWorkingTreeDiffMap` to the `QueryBus` dataclass fields. Add the corresponding `get_commit_diff_map=GetCommitDiffMap(reader),` and `get_working_tree_diff_map=GetWorkingTreeDiffMap(reader),` to the `from_reader` classmethod.

- [ ] **Step 3: Verify**

Run: `uv run python -c "from git_gui.presentation.bus import QueryBus; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Full suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/bus.py
git commit -m "feat(bus): wire GetCommitDiffMap and GetWorkingTreeDiffMap queries"
```

---

## Task 6: Chunked hunk rendering (TDD)

**Files:**
- Test: `tests/presentation/widgets/test_diff_block.py` (new)
- Modify: `git_gui/presentation/widgets/diff_block.py`

- [ ] **Step 1: Write failing test**

Create `tests/presentation/widgets/test_diff_block.py` (ensure `tests/presentation/widgets/__init__.py` exists):

```python
"""Tests for chunked rendering of large hunks in diff_block."""
from __future__ import annotations
from PySide6.QtGui import QTextDocument, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from git_gui.domain.entities import Hunk
from git_gui.presentation.widgets.diff_block import (
    render_hunk_content_lines, make_diff_formats,
)


def _make_cursor(qtbot):
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    return edit.textCursor(), edit


def test_small_hunk_renders_immediately(qtbot):
    """A 50-line hunk is fully rendered in the initial call."""
    lines = [(" ", f"line {i}\n") for i in range(50)]
    hunk = Hunk(header="@@ -1,50 +1,50 @@", lines=lines)
    cursor, edit = _make_cursor(qtbot)
    formats = make_diff_formats()

    render_hunk_content_lines(cursor, hunk, formats)

    assert edit.document().blockCount() >= 50


def test_large_hunk_renders_first_chunk_immediately(qtbot):
    """A 500-line hunk has at least 100 lines rendered immediately."""
    lines = [(" ", f"line {i}\n") for i in range(500)]
    hunk = Hunk(header="@@ -1,500 +1,500 @@", lines=lines)
    cursor, edit = _make_cursor(qtbot)
    formats = make_diff_formats()

    render_hunk_content_lines(cursor, hunk, formats)

    # Immediately after the call, first chunk (100 lines) should be rendered
    assert edit.document().blockCount() >= 100


def test_large_hunk_completes_rendering_after_event_loop(qtbot):
    """A 500-line hunk completes rendering after the event loop processes QTimer callbacks."""
    lines = [(" ", f"line {i}\n") for i in range(500)]
    hunk = Hunk(header="@@ -1,500 +1,500 @@", lines=lines)
    cursor, edit = _make_cursor(qtbot)
    formats = make_diff_formats()

    render_hunk_content_lines(cursor, hunk, formats)

    # Wait for QTimer.singleShot callbacks to fire (4 more ticks for 400 lines)
    qtbot.wait(200)
    assert edit.document().blockCount() >= 500
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/presentation/widgets/test_diff_block.py -v`
Expected: The first test passes (existing behavior), but the large-hunk tests may pass or fail depending on current sync behavior. They should all ultimately pass after the refactor; run to see current state.

- [ ] **Step 3: Refactor render_hunk_content_lines**

In `git_gui/presentation/widgets/diff_block.py`, find `render_hunk_content_lines`. Replace it with a version that extracts the per-line rendering into a helper and schedules chunks for large hunks:

```python
_CHUNK_SIZE = 100


def _render_lines_range(cursor, hunk, formats, start, end) -> None:
    """Render hunk.lines[start:end] into cursor, tracking line numbers."""
    # Re-parse the header to get starting line numbers
    old_line, new_line = parse_hunk_header(hunk.header)
    # Fast-forward past already-rendered lines to keep line numbers accurate
    for origin, _ in hunk.lines[:start]:
        if origin == "+":
            new_line += 1
        elif origin == "-":
            old_line += 1
        else:
            old_line += 1
            new_line += 1

    for origin, content in hunk.lines[start:end]:
        if origin == "+":
            cursor.setBlockFormat(formats.blk_added)
            cursor.setCharFormat(formats.fmt_added)
            prefix = f"     {new_line:>4}  "
            new_line += 1
        elif origin == "-":
            cursor.setBlockFormat(formats.blk_removed)
            cursor.setCharFormat(formats.fmt_removed)
            prefix = f"{old_line:>4}       "
            old_line += 1
        else:
            cursor.setBlockFormat(formats.blk_default)
            cursor.setCharFormat(formats.fmt_default)
            prefix = f"{old_line:>4} {new_line:>4}  "
            old_line += 1
            new_line += 1
        line = content if content.endswith("\n") else content + "\n"
        cursor.insertText(prefix + line)


def render_hunk_content_lines(cursor, hunk: Hunk, formats: DiffFormats) -> int:
    """Insert the +/-/context lines of *hunk* into *cursor*.

    For small hunks (≤ _CHUNK_SIZE lines), renders synchronously.
    For large hunks, renders the first chunk immediately and schedules
    the rest via QTimer.singleShot to keep the UI responsive.

    Returns the number of lines that will ultimately be inserted.
    """
    if not hunk.lines:
        return 0

    total = len(hunk.lines)
    if total <= _CHUNK_SIZE:
        _render_lines_range(cursor, hunk, formats, 0, total)
        return total

    # Render first chunk synchronously
    _render_lines_range(cursor, hunk, formats, 0, _CHUNK_SIZE)

    # Schedule remaining chunks
    from PySide6.QtCore import QTimer
    state = {"start": _CHUNK_SIZE}

    def _next_chunk():
        try:
            start = state["start"]
            end = min(start + _CHUNK_SIZE, total)
            _render_lines_range(cursor, hunk, formats, start, end)
            state["start"] = end
            if end < total:
                QTimer.singleShot(0, _next_chunk)
        except RuntimeError:
            # Cursor's underlying document was destroyed — abort silently
            pass

    QTimer.singleShot(0, _next_chunk)
    return total
```

Make sure `from PySide6.QtCore import QTimer` is at the top of the file (or the local import above works too).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/presentation/widgets/test_diff_block.py -v`
Expected: All 3 PASS.

- [ ] **Step 5: Run full suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/widgets/diff_block.py tests/presentation/widgets/test_diff_block.py
git commit -m "feat(diff_block): chunked rendering for large hunks"
```

---

## Task 7: Skeleton helper in diff_block.py

**Files:**
- Modify: `git_gui/presentation/widgets/diff_block.py`

- [ ] **Step 1: Add skeleton factory**

Append to `git_gui/presentation/widgets/diff_block.py`:

```python
def make_skeleton_container() -> QWidget:
    """Return a QWidget containing 4 gray placeholder bars that mimic diff rows.

    Used as a placeholder inside a file block while the real hunks are being loaded.
    """
    from PySide6.QtWidgets import QVBoxLayout, QFrame
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(4)
    for width_pct in (90, 60, 75, 50):
        bar = QFrame()
        bar.setFixedHeight(10)
        bar.setMinimumWidth(40)
        bar.setStyleSheet(
            "background-color: rgba(128, 128, 128, 40); border-radius: 3px;"
        )
        # Approximate width via size policy; skeleton doesn't need exact proportions
        layout.addWidget(bar)
    return container
```

Make sure `QWidget` is imported at the top (it likely already is).

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from git_gui.presentation.widgets.diff_block import make_skeleton_container; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/diff_block.py
git commit -m "feat(diff_block): add make_skeleton_container helper"
```

---

## Task 8: Lazy loading in DiffWidget (commit view)

**Files:**
- Modify: `git_gui/presentation/widgets/diff.py`

This is the biggest task. Read carefully.

- [ ] **Step 1: Add new state fields in __init__**

In `git_gui/presentation/widgets/diff.py`, in `DiffWidget.__init__`, add these fields right after `self._submodule_paths: set[str] = set()`:

```python
        # Lazy loading state
        self._diff_map: dict[str, list] = {}
        # Each entry: (path, frame_widget, inner_layout, skeleton_widget_or_none)
        self._block_refs: list[tuple[str, QWidget, object, object]] = []
        self._loaded_paths: set[str] = set()

        # Scroll debounce timer
        from PySide6.QtCore import QTimer
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._check_viewport_and_load)
```

Also add `from PySide6.QtCore import QPoint` to the top imports if not present.

- [ ] **Step 2: Connect scroll bar**

In `__init__`, after creating `self._diff_scroll`, connect its vertical scroll bar:

```python
        self._diff_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
```

- [ ] **Step 3: Add helper methods**

Add these methods inside `DiffWidget` (after `_build_file_block`):

```python
    def _build_skeleton_block(self, path: str):
        """Build a file block with a skeleton placeholder. Returns (frame, inner, skeleton)."""
        from git_gui.presentation.widgets.diff_block import make_skeleton_container
        is_submodule = path in self._submodule_paths
        on_click = (
            (lambda p=path: self.submodule_open_requested.emit(p))
            if is_submodule else None
        )
        frame, inner = make_file_block(path, on_header_clicked=on_click)
        skeleton = make_skeleton_container()
        inner.addWidget(skeleton)
        return frame, inner, skeleton

    def _on_scroll(self, value: int) -> None:
        """Debounced scroll handler — restart the timer on every scroll."""
        self._scroll_timer.start()

    def _check_viewport_and_load(self) -> None:
        """Realize any skeleton blocks currently intersecting the viewport."""
        if not self._block_refs or not self._diff_map:
            return
        viewport = self._diff_scroll.viewport()
        vp_rect = viewport.rect()
        for path, frame, inner, skeleton in list(self._block_refs):
            if path in self._loaded_paths:
                continue
            if frame is None:
                continue
            # Translate frame geometry into viewport coordinates
            top_left = frame.mapTo(viewport, QPoint(0, 0))
            frame_rect = frame.rect().translated(top_left)
            if frame_rect.intersects(vp_rect):
                self._realize_block(path, inner, skeleton)

    def _realize_block(self, path: str, inner, skeleton) -> None:
        """Replace the skeleton with real hunk widgets for the given path."""
        if path in self._loaded_paths:
            return
        hunks = self._diff_map.get(path, [])
        # Remove skeleton
        if skeleton is not None:
            inner.removeWidget(skeleton)
            skeleton.deleteLater()
        # Add hunk widgets
        is_submodule = path in self._submodule_paths
        on_click = (
            (lambda p=path: self.submodule_open_requested.emit(p))
            if is_submodule else None
        )
        for hunk in hunks:
            add_hunk_widget(inner, hunk, self._formats, on_header_clicked=on_click)
        self._loaded_paths.add(path)
```

- [ ] **Step 4: Rewrite _render_all_files to use skeletons + background load**

Replace the existing `_render_all_files` method with:

```python
    def _render_all_files(self, oid: str) -> None:
        """Render all file blocks as skeletons immediately, then fetch diffs in background."""
        import threading
        from PySide6.QtCore import QObject, Signal

        self._refresh_submodule_paths()
        self._clear_blocks()
        self._block_refs = []
        self._loaded_paths = set()
        self._diff_map = {}

        row_count = self._diff_model.rowCount()
        for row in range(row_count):
            index = self._diff_model.index(row)
            file_status = self._diff_model.data(index, Qt.UserRole)
            if file_status is None:
                continue
            path = file_status.path
            frame, inner, skeleton = self._build_skeleton_block(path)
            self._diff_layout.addWidget(frame)
            self._block_refs.append((path, frame, inner, skeleton))

        self._diff_layout.addStretch()
        self._diff_scroll.verticalScrollBar().setValue(0)

        # Dispatch background fetch
        queries = self._queries

        class _MapSignals(QObject):
            done = Signal(object)  # dict

        signals = _MapSignals()
        signals.done.connect(self._on_diff_map_loaded)
        self._diff_map_signals = signals  # prevent GC

        def _worker():
            try:
                result = queries.get_commit_diff_map.execute(oid)
            except Exception:
                result = {}
            signals.done.emit(result)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_diff_map_loaded(self, diff_map: dict) -> None:
        """Background fetch finished — store the map and realize visible blocks."""
        self._diff_map = diff_map
        self._check_viewport_and_load()
```

- [ ] **Step 5: Update _render_single_file to use diff_map when available**

Replace `_render_single_file` with:

```python
    def _render_single_file(self, path: str, hunks) -> None:
        """Clear and render one file as a bordered block."""
        self._refresh_submodule_paths()
        self._clear_blocks()
        self._block_refs = []
        self._loaded_paths = set()
        block = self._build_file_block(path, hunks)
        self._diff_layout.addWidget(block)
        self._diff_layout.addStretch()
        self._diff_scroll.verticalScrollBar().setValue(0)
```

This is unchanged from current behavior — single-file view already uses pre-computed hunks, and the caller (`_on_file_selected`) still calls `get_file_diff` for a single file.

- [ ] **Step 6: Verify import**

Run: `uv run python -c "from git_gui.presentation.widgets.diff import DiffWidget; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Run full suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/widgets/diff.py
git commit -m "feat(diff): lazy-load commit diff via skeleton blocks + viewport tracking"
```

---

## Task 9: Lazy loading in HunkDiffWidget (working tree view)

**Files:**
- Modify: `git_gui/presentation/widgets/hunk_diff.py`

Apply the same pattern to `HunkDiffWidget.load_all_files`. The working tree view has a staged/unstaged distinction in the diff map.

- [ ] **Step 1: Add state fields and scroll debounce in __init__**

In `git_gui/presentation/widgets/hunk_diff.py`, in `HunkDiffWidget.__init__`, add after `self._submodule_paths: set[str] = set()`:

```python
        # Lazy loading state (all-files mode)
        self._diff_map: dict[str, dict[str, list]] = {}
        # Each entry: (path, frame_widget, inner_layout, skeleton_widget_or_none, is_untracked)
        self._block_refs: list = []
        self._loaded_paths: set[str] = set()

        # Scroll debounce timer
        from PySide6.QtCore import QTimer
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._check_viewport_and_load)

        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
```

Add `from PySide6.QtCore import QPoint` to the top imports if not present.

- [ ] **Step 2: Replace load_all_files**

Replace the existing `load_all_files` method with:

```python
    def load_all_files(self, paths: list[str]) -> None:
        """Load and display hunks for all given paths with a bordered file block per file."""
        self._current_path = None
        self._all_paths = list(paths)
        if not paths:
            self._clear_layout()
            return

        self._refresh_submodule_paths()
        self._clear_layout()
        self._block_refs = []
        self._loaded_paths = set()
        self._diff_map = {}

        from git_gui.presentation.widgets.diff_block import make_skeleton_container
        for path in paths:
            frame, inner = self._make_file_block(path)
            skeleton = make_skeleton_container()
            inner.addWidget(skeleton)
            self._layout.addWidget(frame)
            spacer = QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Fixed)
            self._layout.addItem(spacer)
            self._block_refs.append((path, frame, inner, skeleton))

        self._layout.addStretch()

        # Dispatch background fetch
        queries = self._queries
        signals = _LoadAllSignals()
        signals.done.connect(self._on_diff_map_loaded)
        self._load_all_signals = signals  # prevent GC

        def _worker():
            try:
                result = queries.get_working_tree_diff_map.execute()
            except Exception:
                result = {}
            signals.done.emit(result)

        threading.Thread(target=_worker, daemon=True).start()
```

Note: the existing `_LoadAllSignals` class emits a list. We need a new signal shape. Add a new signal class at module scope near the top:

```python
class _DiffMapSignals(QObject):
    done = Signal(object)  # dict[str, dict[str, list[Hunk]]]
```

Then change `signals = _LoadAllSignals()` to `signals = _DiffMapSignals()` in the code above.

- [ ] **Step 3: Add new helper methods**

Add these methods to `HunkDiffWidget` (after `_make_file_block`):

```python
    def _on_scroll(self, value: int) -> None:
        """Debounced scroll handler."""
        self._scroll_timer.start()

    def _on_diff_map_loaded(self, diff_map: dict) -> None:
        """Background fetch finished — store the map and realize visible blocks."""
        if self._all_paths is None:
            return
        self._diff_map = diff_map
        self._check_viewport_and_load()

    def _check_viewport_and_load(self) -> None:
        """Realize any skeleton blocks currently intersecting the viewport."""
        if not self._block_refs or not self._diff_map:
            return
        viewport = self._scroll.viewport()
        vp_rect = viewport.rect()
        for path, frame, inner, skeleton in list(self._block_refs):
            if path in self._loaded_paths:
                continue
            if frame is None:
                continue
            top_left = frame.mapTo(viewport, QPoint(0, 0))
            frame_rect = frame.rect().translated(top_left)
            if frame_rect.intersects(vp_rect):
                self._realize_block(path, inner, skeleton)

    def _realize_block(self, path: str, inner, skeleton) -> None:
        """Replace the skeleton with real hunk widgets for the given path."""
        if path in self._loaded_paths:
            return
        entry = self._diff_map.get(path, {"staged": [], "unstaged": []})
        staged_hunks = entry.get("staged", [])
        unstaged_hunks = entry.get("unstaged", [])
        is_untracked = (
            not staged_hunks
            and bool(unstaged_hunks)
            and unstaged_hunks[0].header.startswith("@@ -0,0")
        )
        # Remove skeleton
        if skeleton is not None:
            inner.removeWidget(skeleton)
            skeleton.deleteLater()
        # Add hunks
        for hunk in staged_hunks:
            self._add_hunk_block(hunk, is_staged=True, is_untracked=False,
                                 path=path, parent_layout=inner)
        for hunk in unstaged_hunks:
            self._add_hunk_block(hunk, is_staged=False, is_untracked=is_untracked,
                                 path=path, parent_layout=inner)
        self._loaded_paths.add(path)
```

- [ ] **Step 4: Remove old _on_load_all_done**

The old `_on_load_all_done(self, results: list)` method is no longer used by `load_all_files`. Delete it (the `_render_all_sync` method still uses the old pattern — leave that alone, it's called from post-action refresh paths).

Actually, check callers first:

Run: `uv run python -c "import ast; tree = ast.parse(open('git_gui/presentation/widgets/hunk_diff.py').read()); print([n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)])"`

If `_on_load_all_done` has no remaining callers, delete it. If `_render_all_sync` still exists and is called from elsewhere, leave it as-is (it's the post-action resync path).

- [ ] **Step 5: Verify import**

Run: `uv run python -c "from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Run full suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/widgets/hunk_diff.py
git commit -m "feat(hunk_diff): lazy-load working tree diff via skeletons + viewport tracking"
```

---

## Task 10: Refresh _render_all_sync to use diff map

**Files:**
- Modify: `git_gui/presentation/widgets/hunk_diff.py`

The post-action resync path (`_render_all_sync`) still calls `get_file_diff` per file. Update it to use the batched call.

- [ ] **Step 1: Replace _render_all_sync**

In `git_gui/presentation/widgets/hunk_diff.py`, replace `_render_all_sync` with:

```python
    def _render_all_sync(self) -> None:
        """Post-action refresh for all-files mode."""
        if self._all_paths is None:
            return
        # Reload via the lazy pipeline
        self.load_all_files(self._all_paths)
```

- [ ] **Step 2: Run full suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/hunk_diff.py
git commit -m "refactor(hunk_diff): route _render_all_sync through lazy load pipeline"
```

---

## Task 11: Manual acceptance

- [ ] **Step 1: Launch the app**

Run: `uv run python main.py`

- [ ] **Step 2: Verify commit view scenarios**

1. Click a commit with many files (e.g. a merge commit or large refactor) → skeletons appear instantly; diffs fill in as you scroll.
2. Click a commit with a single huge file (e.g. a large generated file diff) → diff appears progressively; scroll bar stays responsive during rendering.
3. Switch between commits quickly → no UI freeze, no stale skeletons.

- [ ] **Step 3: Verify working tree scenarios**

1. Make many uncommitted changes (e.g. touch many files) → skeletons appear instantly; hunks load as you scroll.
2. Single file with a huge modification → progressive rendering.
3. Mix of staged, unstaged, conflicted, and untracked files → all appear in the list with correct badges and diffs.

- [ ] **Step 4: Commit any fixes**

If manual testing reveals issues, fix and commit with descriptive messages.

---

## Out of Scope

- Cross-commit diff caching (each commit view recomputes; fast enough with batching)
- Cancellation of in-flight background fetches on navigation (existing code doesn't handle this either)
- Binary-file diff rendering improvements
- Merging `diff.py` and `hunk_diff.py` into one widget (separate refactor)
