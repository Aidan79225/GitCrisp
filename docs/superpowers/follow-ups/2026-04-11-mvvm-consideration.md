# Follow-up: Presentation-layer refactoring (MVVM consideration)

**Date:** 2026-04-11
**Status:** Not planned as a standalone task. Apply opportunistically when touching affected widgets.

## Context

During the lazy diff loading work, the question came up of whether the project should refactor its presentation layer to a full MVVM (Model-View-ViewModel) pattern. The conclusion was **no full rewrite**, but targeted extractions should happen opportunistically.

## Why not a full MVVM rewrite

1. **Clean Architecture already covers most of MVVM's benefits.** The `application/` layer is effectively the Model side, and `queries` / `commands` are already testable in isolation from Qt.
2. **Qt's signal/slot system is already a binding layer.** A PySide6 ViewModel ends up being "a QObject that emits signals" — which is what widgets already are. Adding a separate ViewModel doubles the signal plumbing.
3. **Big refactors across ~15 widget files have a large blast radius for incremental benefit.**

## Current pain points that a targeted refactor could fix

- `DiffWidget`, `WorkingTreeWidget`, and `HunkDiffWidget` each mix three responsibilities: layout, threading / state machines, and business logic.
- Tests bypass widget `__init__` with `WidgetClass.__new__(WidgetClass)` hacks because the widgets cannot be constructed in isolation.
- Threading patterns (background worker → Qt signal → UI update) are duplicated across several widgets.

## Recommended approach: extract loaders / state machines

When touching a widget that feels too complex, extract its state machine or loader into a pure-Python class that the widget wraps. Candidates today:

- **`CommitDiffLoader`** — owns the skeleton/realize/viewport logic currently in `DiffWidget._check_viewport_and_load`, `_realize_block`, and the background `get_commit_diff_map` fetch. The widget becomes "connect the loader to a layout." The loader is unit-testable without Qt.
- **`WorkingTreeCommitFlow`** — owns the merge/rebase continue/abort state and message handling currently in `WorkingTreeWidget._on_commit`, `_on_abort_clicked`, and the related main-window handlers.
- **`MergeExecutor`** — owns the "merge analysis → open dialog → execute command" flow from `main_window._on_merge` and `_on_merge_commit`.

Each extraction should:
1. Be a pure-Python class (no Qt widgets inside).
2. Expose a clear interface: what it does, how you use it, what it depends on.
3. Come with its own unit tests that do not need `pytest-qt`.
4. Let the host widget shrink to layout + binding.

## Trigger

Do not schedule this work as a standalone task. Apply it when:

- A widget exceeds ~300 lines and mixes concerns, OR
- Writing a test for a widget feature requires bypassing `__init__`, OR
- A bug fix reveals that the same state logic exists in two widgets.

Over time the codebase will gain MVVM-shaped extractions where they are actually earning their keep, without a big-bang rewrite.
