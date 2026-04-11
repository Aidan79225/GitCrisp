# Follow-up: Project review recommendations

**Date:** 2026-04-11
**Status:** Not planned as standalone tasks. Pick opportunistically or split into specs as needed.

## Context

A project-wide review of GitStack turned up nine recommendations, grouped by priority. The review found a healthy Clean Architecture (strict layer boundaries, 77% test density, no TODO/FIXME debt) but a handful of small improvements and one documented refactor candidate (see `2026-04-11-mvvm-consideration.md`).

This doc captures the recommendations so they are not lost.

## Top priority

### 1. Pin upper bounds on `pygit2` and `pyside6`

`pyproject.toml` currently has:

```toml
"pygit2>=1.19.2",
"pyside6>=6.11.0",
```

Major version bumps of either could silently break the build or rendering. Change to:

```toml
"pygit2>=1.19.2,<2",
"pyside6>=6.11.0,<7",
```

Two-line change, no brainstorming needed, can ship as-is.

### 2. Replace bare `except Exception: pass` with warning logs

`git_gui/infrastructure/pygit2_repo.py` has about ten bare-except traps around git operations (for example, in `get_working_tree_diff_map`, `get_file_diff`, the conflict-fallback path, and submodule lookups). The graceful degradation is correct, but the silent failure mode makes real bugs invisible.

Wire in `logging` (stdlib, no new dependency), log at WARNING level with the path and exception message, and keep the fallback behavior unchanged. Gives future bug reports breadcrumbs.

### 3. Persistent indicator during slow / remote operations

`main_window.py` already tracks `_remote_running` but does not show it to the user. Push, pull, fetch, and fetch-all-prune can take seconds with no visible feedback, so users click twice. A small spinner or status-bar text toggled on `_remote_running` would prevent this.

## Medium priority

### 4. Extract `CommitDiffLoader` when next touching `diff.py` or `hunk_diff.py`

`git_gui/presentation/widgets/diff.py` (384 LOC), `hunk_diff.py` (393 LOC), and `working_tree.py` (408 LOC) all duplicate the viewport-tracking + skeleton-realization pattern from the lazy-diff work. See `2026-04-11-mvvm-consideration.md` for the recommended extraction: a pure-Python class the widget wraps. Opportunistic — do it the next time a bug fix or feature lands in one of those files.

### 5. `get_working_tree_diff_map` staged-diff fallback needs logging

The staged side of `get_working_tree_diff_map` is wrapped in `try/except Exception: pass` because `index.diff_to_tree` can raise when the index has conflicts. If the exception handling regresses, staged hunks silently disappear during a conflict and there is no way to diagnose it. Combine with #2: log the exception, keep the fallback.

### 6. Core keyboard shortcuts

Only `F5` (reload) exists today. Five small, independent bindings would materially improve daily use:

- Enter → stage / unstage the currently selected file
- Delete → discard the currently selected hunk
- Ctrl+Enter → commit
- Ctrl+P → quick repo switch
- Esc → deselect current file

Each is ~30 minutes of work and can land separately.

## Lower priority

### 7. Missing git-client features

No blame view, no history search, no reflog viewer, no cherry-pick UI. Each is its own project. Worth noting: the `2026-04-04-operation-log.md` plan looks unshipped — could be a natural next feature if you want a rebase / undo affordance before tackling blame or search.

### 8. Widget test coverage is thin

Only ~311 LOC of presentation tests against ~3,100 LOC of widgets / models / theme code. Domain, application, and infrastructure layers are well covered. The blocker is the same as #4: until the loader / state-machine logic is extracted from the big widgets, tests have to bypass `__init__` with `WidgetClass.__new__`. Extracting loaders makes widget tests cheap.

### 9. Accessibility is zero

No `setAccessibleName` / `setAccessibleDescription` calls anywhere. Graph, diff, and branch tree are opaque to screen readers. Not urgent for a personal project; cheap per-widget fix if it becomes a priority.

## Not recommended

- **Full MVVM refactor** — already rejected in `2026-04-11-mvvm-consideration.md`; the targeted-extraction approach is correct.
- **Split `pygit2_repo.py`** (1066 LOC) — it is cohesive, not tangled. Splitting for its own sake adds navigation cost without a clear win.
- **Big `main_window.py` cleanup** (746 LOC) — it is orchestration glue; extracting pieces does not improve clarity.
