# Toolbar Layout + Stash Button Design

## Goal

Reposition the 4 existing toolbar buttons (Reload, Push, Pull, Fetch) to the left, and add a new Stash button on the right. The Stash button shows a confirmation dialog before stashing. The Stash button is hidden when the working tree has no changes (0 hunks).

## Changes

### `graph.py` — Header bar layout

Current layout: `———stretch——— [Reload][Push][Pull][Fetch]`

New layout: `[Reload][Push][Pull][Fetch] ———stretch——— [Stash]`

- Remove `header_bar.addStretch()` before the loop
- Add `header_bar.addStretch()` after the loop
- Add a Stash button using `arts/ic_stash.svg`, tooltip "Stash"
- New signal: `stash_requested = Signal()`
- Stash button click emits `stash_requested`
- Store a reference to the Stash button as `self._stash_btn`
- Add method `set_stash_visible(visible: bool)` that calls `self._stash_btn.setVisible(visible)`

### `main_window.py` — Stash wiring

- Connect `self._graph.stash_requested` to `_on_stash_requested`
- `_on_stash_requested` handler:
  1. Show `QMessageBox.question` with title "Stash Changes" and text: "Would you like to stash all uncommitted changes? This will save your modifications and revert the working directory to a clean state."
  2. On Yes: get current branch name, call `self._commands.stash.execute(f"WIP on {branch}")`, log it, reload
  3. On No: do nothing
- Update stash button visibility on reload: after `self._graph.reload()`, check `self._queries.is_dirty.execute()` and call `self._graph.set_stash_visible(is_dirty)`
- Also update visibility after commit completed and working tree empty signals

### Visibility rule

The Stash button is visible only when the working tree is dirty (has uncommitted changes). Check `is_dirty` after every reload cycle.
