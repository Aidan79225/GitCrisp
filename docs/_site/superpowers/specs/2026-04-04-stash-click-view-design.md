# Stash Click-to-View Design

## Goal

Clicking a stash item in the sidebar shows the stash's content (file list + diff) in the right panel's DiffWidget, deselecting the graph. Clicking a graph commit clears the stash highlight.

## Approach

A stash is internally a git commit. Its oid is already stored in `Stash.oid`. The existing `DiffWidget.load_commit(oid)` and underlying `get_commit_files` / `get_file_diff` work with any commit oid, including stash commits. No domain, port, infrastructure, or query changes are needed.

## Changes

### `sidebar.py`

- Add signal: `stash_clicked = Signal(str)` — emits the stash oid.
- In `_add_section`, stash items already store `index` as the value. The stash oid needs to be passed as the 4th tuple element so it gets set on `_TARGET_OID_ROLE`.
- In `_on_click`, when the item kind is `"stash"`, emit `stash_clicked` with the oid from `_TARGET_OID_ROLE`.
- Add method `clear_stash_selection()` — calls `self._tree.clearSelection()` to remove visual highlight.

### `graph.py`

- Add method `clear_selection()` — calls `self._view.clearSelection()` to deselect the current graph row.

### `main_window.py`

- Connect `sidebar.stash_clicked` to new handler `_on_stash_clicked(oid)`:
  1. `self._graph.clear_selection()`
  2. `self._right_stack.setCurrentIndex(0)`
  3. `self._diff.load_commit(oid)`
- In existing `_on_commit_selected`, add `self._sidebar.clear_stash_selection()`.

## Commit detail header

Displays the stash's underlying commit metadata (author, date, message) as-is, since a stash is a regular commit internally.

## Mutual exclusion

- Stash click → graph deselected, stash highlighted
- Graph click → stash deselected, graph row highlighted

This ensures exactly one item is visually selected at any time.
