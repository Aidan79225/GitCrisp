# ViewportBlockLoader Extraction — Design

**Status:** Draft
**Date:** 2026-04-13

## Background

`DiffWidget` (`diff.py`, 425 LOC) and `HunkDiffWidget` (`hunk_diff.py`, 408 LOC) each implement nearly identical viewport-tracking / skeleton-realization logic (~60 lines each) for the lazy diff loading feature. This duplication is the top refactor candidate from the project review follow-ups (`2026-04-11-project-review.md` item #4) and the MVVM consideration doc (`2026-04-11-mvvm-consideration.md`).

The duplicated code includes: `_block_refs` / `_loaded_paths` / `_diff_map` state management, a 50ms scroll-debounce timer, viewport-intersection checking via `frame.mapTo(viewport, QPoint(0,0))`, single-block-per-call realization with `QTimer.singleShot(0, ...)` rescheduling, and `RuntimeError` safety for stale frame references.

`working_tree.py` delegates to `HunkDiffWidget` and is not directly involved.

## Goals

- Eliminate the duplicated viewport-tracking / skeleton-realization logic.
- Make the viewport logic testable without constructing real diff widgets.
- Preserve each widget's domain-specific realization behavior (DiffWidget uses `add_hunk_widget`; HunkDiffWidget uses `_add_hunk_block` with checkboxes and discard buttons).
- Do NOT extract the background-fetch pattern (it's only ~10 lines per widget, differs in which query is called, and would add unnecessary complexity to the loader).

## Architecture

### New class: `ViewportBlockLoader`

**File:** `git_gui/presentation/widgets/viewport_block_loader.py`

A composition-based helper that the widget creates and owns. Each widget provides its scroll area and a `realize_fn` callback; the loader handles all the viewport-tracking state.

**Constructor:**

```
ViewportBlockLoader(
    scroll_area: QScrollArea,
    realize_fn: Callable[[str, QVBoxLayout, QWidget | None, Any], None],
)
```

- `scroll_area`: the widget's QScrollArea whose viewport is used for intersection checks and whose vertical scroll bar is connected to the debounced timer.
- `realize_fn(path, inner_layout, skeleton_or_none, diff_entry)`: the widget's callback that replaces the skeleton with real hunk widgets. `diff_entry` is `self._diff_map[path]` — the loader does not interpret its shape (could be `list[Hunk]` or `{"staged": [...], "unstaged": [...]}`).

**Internal state:**

- `_block_refs: list[tuple[str, QFrame, QVBoxLayout, QWidget | None]]` — `(path, frame, inner_layout, skeleton)` for each file block.
- `_loaded_paths: set[str]` — paths whose blocks have been realized.
- `_diff_map: dict[str, Any]` — the fetched diff data, keyed by path.
- `_scroll_timer: QTimer` — 50ms single-shot debounce timer connected to `_check_viewport`.

**Public methods:**

- `set_blocks(block_refs: list[tuple[str, QFrame, QVBoxLayout, QWidget | None]])` — called after the widget creates skeleton frames. Resets `_loaded_paths` and `_diff_map`.
- `set_diff_map(diff_map: dict[str, Any])` — called when the background fetch completes. Stores the map and schedules `_check_viewport` via `QTimer.singleShot(0, ...)` (deferred one tick so Qt can lay out the skeletons).
- `clear()` — resets `_block_refs`, `_loaded_paths`, and `_diff_map`. Called by the widget's `_clear_blocks` / `_clear_layout`.

**Private methods:**

- `_on_scroll(value: int)` — restarts `_scroll_timer`.
- `_check_viewport()` — iterates `_block_refs`, finds the first block whose frame intersects the scroll area's viewport and is not yet in `_loaded_paths`. Calls `realize_fn(path, inner, skeleton, diff_map[path])`. Reschedules itself via `QTimer.singleShot(0, ...)` to realize the next block after Qt processes the layout change. Wraps `frame.mapTo(...)` in `try/except RuntimeError` to handle stale frame references silently.

### Widget changes

**DiffWidget (`diff.py`):**

Remove:
- `self._diff_map`, `self._block_refs`, `self._loaded_paths` fields
- `self._scroll_timer` and its setup
- `_on_scroll()`, `_check_viewport_and_load()`, `_realize_block()`, `_on_diff_map_loaded()` methods
- Scroll bar connection

Add:
- `self._loader = ViewportBlockLoader(self._diff_scroll, self._realize_block)` in `__init__`
- `_realize_block(path, inner, skeleton, hunks)` — receives `list[Hunk]`, removes skeleton, calls `add_hunk_widget` for each hunk (same logic as the current `_realize_block`, just takes `hunks` as a param instead of looking up `_diff_map`)

Update:
- `_render_all_files`: after creating skeletons, call `self._loader.set_blocks(block_refs)`, then dispatch background thread. On thread done, call `self._loader.set_diff_map(result)`.
- `_clear_blocks`: call `self._loader.clear()` after clearing the layout.
- `_render_single_file`: call `self._loader.clear()` (resets the lazy-loading state when switching to single-file mode).

**HunkDiffWidget (`hunk_diff.py`):**

Same pattern. The `realize_fn` receives `{"staged": [...], "unstaged": [...]}` and calls `_add_hunk_block` with the checkbox/discard logic.

Remove same set of duplicated fields and methods. Add loader in `__init__`, provide `_realize_block` callback.

## Testing

**New file:** `tests/presentation/widgets/test_viewport_block_loader.py`

Tests construct a `ViewportBlockLoader` with a mock `QScrollArea` (from `pytest-qt`) and a mock `realize_fn`. Key test cases:

1. **`test_set_diff_map_triggers_check`** — call `set_diff_map`, verify `realize_fn` is called after event loop tick.
2. **`test_realizes_one_block_per_check`** — with 3 blocks all visible, after one event loop tick only 1 block is realized (serial realization).
3. **`test_skips_loaded_paths`** — manually add a path to `_loaded_paths`, verify it's skipped.
4. **`test_stale_frame_is_skipped`** — delete a frame widget, verify no crash and the block is skipped.
5. **`test_clear_resets_state`** — call `clear()`, verify `_block_refs` and `_loaded_paths` are empty.

Existing tests in `tests/presentation/widgets/test_diff_block.py` (chunked rendering) are unaffected.

## File change list

New:
- `git_gui/presentation/widgets/viewport_block_loader.py`
- `tests/presentation/widgets/test_viewport_block_loader.py`

Modified:
- `git_gui/presentation/widgets/diff.py` — replace inline viewport logic with loader
- `git_gui/presentation/widgets/hunk_diff.py` — same

## Out of scope

- Extracting the background-fetch pattern (only ~10 lines per widget, differs in query).
- Touching `working_tree.py` (it delegates to HunkDiffWidget).
- Merging `diff.py` and `hunk_diff.py` into one widget.
