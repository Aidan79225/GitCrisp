# Reload Toolbar Button — Design Spec
_Date: 2026-04-03_

## Overview

Add a "Reload" button to a toolbar at the top of `MainWindow` that refreshes the entire UI (commit graph, sidebar branches/stashes) by calling the existing `_reload()` method.

---

## Architecture

Single change to `git_gui/presentation/main_window.py`:

- Add a `QToolBar` via `self.addToolBar("Main")`
- Add a `QAction("Reload", self)` to the toolbar
- Set keyboard shortcut: `QKeySequence(Qt.Key_F5)`
- Connect `action.triggered` to `self._reload()`

No new files. No new tests needed — `_reload()` is already exercised by existing signal paths.

---

## Files Changed

| File | Change |
|------|--------|
| `git_gui/presentation/main_window.py` | Add toolbar with Reload action |
