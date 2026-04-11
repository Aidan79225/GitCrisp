# Lazy Diff Loading — Design

**Status:** Draft
**Date:** 2026-04-11

## Background

Loading a commit with many files or large diffs currently freezes the UI. The root cause is in `DiffWidget.load_commit` / `_render_all_files`:

1. The commit metadata, file list, and every file's diff are fetched synchronously on the UI thread.
2. `_render_all_files` loops through every file and calls `get_file_diff(oid, path)` once per file.
3. `get_file_diff` computes the full tree diff (`self._repo.diff(parent.tree, commit.tree)`) **every time**, then linearly searches for the matching patch. N files = N full tree diffs, each redundant.
4. Each hunk is rendered into a `QTextEdit` in one call, so a single 10k-line diff blocks rendering regardless of how many files.

The working tree's `HunkDiffWidget.load_all_files` is slightly better — it runs sequentially on a background thread — but still calls `get_file_diff` per file and has no skeleton/lazy rendering.

## Goals

- Make commit and working-tree views responsive regardless of file count or diff size.
- Reuse the same loading pipeline for both views.
- Avoid cache invalidation complexity: no long-lived diff cache; each load computes once.
- No "diff too large, click to load" walls — everything loads progressively.

## Approach

**Three combined techniques:**

1. **Batched diff fetch** — one call to the reader computes the full tree diff once and returns all hunks keyed by path. N file lookups become 1 tree diff.
2. **Viewport-triggered lazy rendering** — file blocks render as skeletons immediately; each block's hunks are inserted into the widget tree only when it enters the viewport.
3. **Chunked hunk rendering** — hunks larger than 100 lines render in 100-line batches spaced across event-loop ticks, keeping each tick ≤ 16ms.

## Architecture

### Domain (`domain/ports.py`)

`IRepositoryReader` gains two methods:

```
get_commit_diff_map(oid: str) -> dict[str, list[Hunk]]
get_working_tree_diff_map() -> dict[str, dict[str, list[Hunk]]]
```

- `get_commit_diff_map` returns `{path: [Hunk, ...]}` for every changed file in the commit. Computed via a single `self._repo.diff(parent.tree, commit.tree)` call (or against an empty tree for the first commit).
- `get_working_tree_diff_map` returns `{path: {"staged": [...], "unstaged": [...]}}`. Computed via one call to `self._repo.index.diff_to_tree(HEAD.tree)` for the staged side and one call to `self._repo.diff()` for the unstaged side. Conflicted and untracked files are handled via the existing `_synthesise_conflict_hunk` / `_synthesise_untracked_hunk` helpers, so they appear in the map with the same shape.

### Infrastructure (`infrastructure/pygit2_repo.py`)

Implement the two methods. Key invariant: **exactly one call to `self._repo.diff(...)` per method**, no per-file iteration calling `diff()` again.

### Application (`application/queries.py`)

Two new queries mirroring the reader methods:

```
GetCommitDiffMap    (reader) → execute(oid) -> dict[str, list[Hunk]]
GetWorkingTreeDiffMap (reader) → execute() -> dict[str, dict[str, list[Hunk]]]
```

### Presentation — `presentation/bus.py`

Wire both new queries into `QueryBus`.

### Presentation — `presentation/widgets/hunk_diff.py` (major refactor)

**New internal state:**

- `self._diff_map` — the last loaded diff map (path → hunks, or path → {staged, unstaged}).
- `self._block_refs` — `list[tuple[str, QFrame, QVBoxLayout, QWidget]]` storing `(path, frame, inner_layout, skeleton_container)` for each file block in current mode. Used by the viewport scan to find which blocks need realization.
- `self._loaded_paths` — set of paths whose hunks have been rendered into the layout.
- `self._scroll_timer` — `QTimer` used for debouncing scroll events (interval 50ms, single-shot mode).

**New methods:**

- `_render_skeleton_block(path, frame, inner) -> QWidget` — creates a skeleton container with 3–5 gray placeholder bars and adds it to `inner`. Returns the container so it can be removed later.
- `_realize_block(path)` — looks up `self._diff_map[path]`, removes the skeleton container, and calls the existing `_add_hunk_block` pattern to render real hunks. For working-tree mode, splits the dict into staged and unstaged buckets and sets `is_staged`/`is_untracked` flags as today. Marks the path as loaded.
- `_check_viewport_and_load()` — iterates `self._block_refs`, computes `frame.mapTo(self._scroll_area_viewport, QPoint(0, 0))` + geometry to find blocks currently visible, and calls `_realize_block` for any unloaded ones.
- `_on_scroll(value)` — slot for the scroll bar's `valueChanged`. Restarts `self._scroll_timer` (single-shot, 50ms) which fires `_check_viewport_and_load`. Debouncing prevents running the intersection check on every pixel.

**Modified methods:**

- `load_all_files(paths)` (working tree mode):
  1. Clear layout and `_block_refs`.
  2. For each path, build a file block via `make_file_block`, then add a skeleton to it.
  3. Append the block frame to the layout and record `(path, frame, inner, skeleton)` in `_block_refs`.
  4. Add the stretch at the end.
  5. Dispatch a background thread that calls `get_working_tree_diff_map()`.
  6. On the UI thread `done` signal, store the result in `self._diff_map`, then call `_check_viewport_and_load()` to realize any already-visible blocks.

- New method `load_commit_files(oid, files)` (commit mode, replaces the per-file loop):
  - Same pattern, but calls `get_commit_diff_map(oid)` instead.

**Scroll-area integration:**

- `HunkDiffWidget` is already embedded in a `QScrollArea` by its parent widget. Access the scroll area via `self.parent()` or have the parent hand it in explicitly. We'll pass the scroll area to `set_scroll_area(scroll_area)` at construction / wiring time, and connect `scroll_area.verticalScrollBar().valueChanged` to `_on_scroll`.

### Presentation — `presentation/widgets/diff.py` (commit view)

- `_render_all_files(files)` replaced: instead of looping `get_file_diff` and rendering synchronously, call `self._hunk_diff.load_commit_files(oid, files)`. The commit detail header (message, author, etc.) still renders synchronously — that's fast.
- If `diff.py` and `hunk_diff.py` have diverged significantly in rendering logic, this task includes a minor cleanup to route commit-file rendering through `HunkDiffWidget.load_commit_files`.

### Presentation — `presentation/widgets/diff_block.py`

`render_hunk_content_lines` becomes cooperative for large hunks:

```
CHUNK_SIZE = 100

def render_hunk_content_lines(cursor, hunk, formats):
    if len(hunk.lines) <= CHUNK_SIZE:
        # existing synchronous path
        return

    # Render first chunk immediately, schedule rest
    _render_chunk(cursor, hunk, formats, 0, CHUNK_SIZE)
    remaining_start = CHUNK_SIZE

    def _next_chunk():
        nonlocal remaining_start
        end = min(remaining_start + CHUNK_SIZE, len(hunk.lines))
        _render_chunk(cursor, hunk, formats, remaining_start, end)
        remaining_start = end
        if remaining_start < len(hunk.lines):
            QTimer.singleShot(0, _next_chunk)

    QTimer.singleShot(0, _next_chunk)
```

The cursor must remain valid across ticks — since it points into a `QTextDocument` that stays alive while the widget is visible, this works. If the widget is destroyed mid-render, the scheduled callbacks become no-ops (wrap in a weakref check).

## Data flow (commit view)

1. User clicks a commit → `DiffWidget.load_commit(oid)` runs (threaded worker fetches commit detail + file list only).
2. Worker returns → UI thread builds header + calls `HunkDiffWidget.load_commit_files(oid, files)`.
3. `load_commit_files` synchronously creates skeleton blocks for all files and dispatches a background thread to fetch `get_commit_diff_map(oid)`.
4. Worker returns → UI thread stores `self._diff_map`, then calls `_check_viewport_and_load()`.
5. Visible blocks are realized (skeletons replaced by hunks). Large hunks schedule chunked rendering.
6. User scrolls → debounced `_on_scroll` fires `_check_viewport_and_load` → newly visible blocks are realized.

## Testing

### Infrastructure

`tests/infrastructure/test_reads.py`:

- `test_get_commit_diff_map_returns_all_files` — create a commit with 3 modified files; assert dict has all 3 paths and each value is a non-empty list of hunks.
- `test_get_commit_diff_map_initial_commit` — first commit (no parent); assert diff against empty tree produces all files as additions.
- `test_get_working_tree_diff_map_staged_and_unstaged` — stage one change and leave another unstaged; assert result has both with the correct sub-dict keys.
- `test_get_working_tree_diff_map_includes_conflicted` — create a merge conflict; assert the conflicted file appears in the map with non-empty hunks.
- `test_get_working_tree_diff_map_includes_untracked` — create an untracked file; assert it appears in the map with synthesized hunks.

### Application

`tests/application/test_queries.py`:

- `test_get_commit_diff_map_passthrough` — fake reader, confirm query delegates.
- `test_get_working_tree_diff_map_passthrough`.

### Presentation

`tests/presentation/widgets/test_diff_block.py` (new or extend):

- `test_small_hunk_renders_immediately` — 50-line hunk; after `render_hunk_content_lines` returns, document contains all 50 lines.
- `test_large_hunk_splits_into_chunks` — 500-line hunk; immediately after the call, document contains only the first 100 lines; after `qtbot.wait(100)` / event loop processing, all 500 lines are present.

### Manual acceptance

- Commit with 100 files → skeletons appear instantly; diffs fill in as user scrolls; no UI freeze.
- Commit with a single 10k-line file → diff appears in chunks; scroll bar stays responsive during rendering.
- Working tree with many changes → same progressive behavior.
- Fast scroll through many files → debounced loader only realizes blocks after scroll settles; no jank.

## File change list

Modified:
- `git_gui/domain/ports.py`
- `git_gui/infrastructure/pygit2_repo.py`
- `git_gui/application/queries.py`
- `git_gui/presentation/bus.py`
- `git_gui/presentation/widgets/hunk_diff.py`
- `git_gui/presentation/widgets/diff.py`
- `git_gui/presentation/widgets/diff_block.py`

Test files modified:
- `tests/infrastructure/test_reads.py`
- `tests/application/test_queries.py`
- `tests/presentation/widgets/test_diff_block.py` (new or extend)

## Out of scope

- Cross-commit diff caching (each commit view recomputes; fast enough with batching)
- Cancellation of in-flight background fetches when user navigates away (existing code doesn't handle this either)
- Binary-file diff rendering improvements
- Merging `diff.py` and `hunk_diff.py` into one widget — they diverge in commit-view vs working-tree semantics; a full merge is a separate refactor.
