# `Pygit2Repository` Split — Design

**Date:** 2026-04-18
**Status:** Proposed

## Goal

Break the 1,422-line `git_gui/infrastructure/pygit2_repo.py` into a set of focused mixin files so that no single file exceeds ~330 lines. The concrete class `Pygit2Repository` stays the one public symbol; its external behavior is unchanged. This is a mechanical code reorganization — no logic edits.

## Scope

- Create a new subpackage `git_gui/infrastructure/pygit2/` containing ten mixin modules plus a pure-helpers module and a composite class module.
- Delete the old `git_gui/infrastructure/pygit2_repo.py`.
- Update the one importer (`main.py`) to use the new subpackage path.
- Add two lightweight structural tests that guard the new layout.

## UX Decisions

| Concern | Decision |
|---|---|
| Split style | Mixins. Each concern is a class that adds methods to `self`; the composite `Pygit2Repository(BranchOps, CommitOps, ...)` inherits from all of them. |
| External API | Unchanged. Callers keep writing `Pygit2Repository(path)` and calling the same methods. |
| Port coverage | Unchanged. Still implements `IRepositoryReader` and `IRepositoryWriter` end-to-end. |
| Adapter / facade alternative | Rejected. It would add ~200 lines of passthrough methods and wouldn't meaningfully reduce cognitive load. |
| Port splitting | Out of scope. `IRepositoryReader` / `IRepositoryWriter` stay monolithic. |
| Scope of change | One PR containing the entire split. Mechanical, and the existing 497-test suite is the safety net. |
| Location | New subpackage `git_gui/infrastructure/pygit2/` so the ten related modules live together. |
| Old file | `git_gui/infrastructure/pygit2_repo.py` deleted — no backwards-compat re-export. Only consumer (`main.py`) is updated in the same commit. |

## Approach

Each of the ten concern groups identified during brainstorming becomes a mixin class in its own file. `Pygit2Repository` is a composite that inherits from all ten and contains only `__init__`. Shared instance helpers (e.g., `_get_signature`, `_run_git`, `_detect_diverged_submodules`) are placed on whichever mixin is their primary consumer; other mixins call them via `self.` and Python's MRO resolves the call. Pure module-level helpers move to `_helpers.py` and are imported by whichever mixins need them.

No logic is rewritten. Every method keeps its current body, docstring, exception behavior, and dependency footprint. The only edits are:

1. Moving methods from `Pygit2Repository` in `pygit2_repo.py` into mixin classes.
2. Rewriting imports so the mixins pick up module-level helpers from `_helpers.py`.
3. Adding the composite-class definition with the mixin MRO.
4. Updating `main.py`'s single import line.

## Architecture & files touched

**New files (all under `git_gui/infrastructure/pygit2/`):**

```
git_gui/infrastructure/pygit2/
├── __init__.py               # re-exports Pygit2Repository
├── repository.py             # class Pygit2Repository(...mixins): — __init__ only (~60 LOC)
├── branch_ops.py             # ~180 LOC
├── commit_ops.py             # ~210 LOC — commit reads, commit/amend/reset, cherry-pick, revert
├── diff_ops.py               # ~320 LOC — diff/hunk/file-status + synthesis helpers
├── stage_ops.py              # ~140 LOC — stage/unstage/hunk stage/discard
├── tag_ops.py                # ~85 LOC — tag read/write, push_tag, delete_remote_tag
├── stash_ops.py              # ~48 LOC
├── merge_rebase_ops.py       # ~220 LOC — merge/rebase/interactive/abort/continue
├── remote_ops.py             # ~100 LOC — list/add/remove/rename/push/pull/fetch
├── submodule_ops.py          # ~130 LOC — add/remove/set_url + gitdir/diverge helpers
├── repo_state_ops.py         # ~80 LOC — HEAD, state, MERGE_HEAD, conflicts, _git_env
└── _helpers.py               # pure functions from today's module-level helpers
```

**Deleted:** `git_gui/infrastructure/pygit2_repo.py`.

**Modified:** `main.py` — one import line changes from `from git_gui.infrastructure.pygit2_repo import Pygit2Repository` to `from git_gui.infrastructure.pygit2 import Pygit2Repository`.

**New tests:**
```
tests/infrastructure/test_pygit2_package.py
tests/infrastructure/test_pygit2_ports.py
```

**Not touched:** domain, application, all presentation widgets, dialogs, menus, theme, QSS, README.

## Home for shared instance-methods

Each shared helper lives on its primary-consumer mixin. Other mixins call it through `self.`, resolving via MRO. No base class.

| Helper | Mixin home | Callers |
|---|---|---|
| `_get_signature()` | `CommitOps` | `CommitOps`, `TagOps`, `StashOps`, `MergeRebaseOps` |
| `_git_env` (property) | `RepoStateOps` | every mixin that shells out |
| `_run_git(*args)` | `RemoteOps` | `RemoteOps`, `MergeRebaseOps`, `TagOps`, `StageOps`, `CommitOps` (via `get_commit_stats`) |
| `_detect_diverged_submodules()` | `SubmoduleOps` | `DiffOps` (`get_working_tree_diff_map`), `StageOps` (`get_working_tree`) |
| `_build_hunk_patch(path, hunk_header, staged)` | `StageOps` | `StageOps`, `DiffOps` |
| `_diff_workfile_against_head(path)` | `DiffOps` | `DiffOps` internally |
| `_merge_oid(...)` | `MergeRebaseOps` | `MergeRebaseOps` internally |
| `_rebase_onto(target_oid)` | `MergeRebaseOps` | `MergeRebaseOps` internally |
| `_submodule_cli()` factory | `SubmoduleOps` | `SubmoduleOps` internally |

## Pure module-level helpers (→ `_helpers.py`)

| Function | Current home | Importing mixins |
|---|---|---|
| `_commit_to_entity(commit)` | `pygit2_repo.py:42` | `CommitOps`, `MergeRebaseOps` |
| `_diff_to_hunks(patch)` | `pygit2_repo.py:53` | `CommitOps`, `DiffOps`, `StageOps` |
| `_map_statuses(flags)` | `pygit2_repo.py:33` | `DiffOps`, `StageOps` |
| `_synthesise_untracked_hunk(workdir, path)` | `pygit2_repo.py:65` | `DiffOps` |
| `_synthesise_conflict_hunk(workdir, path)` | `pygit2_repo.py:94` | `DiffOps` |
| `_resolve_gitdir(path)` | `pygit2_repo.py:139` | `SubmoduleOps`, `RepoStateOps` (used in `__init__` chain) |
| `_parse_gitmodules_paths(workdir)` | `pygit2_repo.py:206` | `SubmoduleOps` |
| `_read_submodule_head_oid(parent_workdir, sub_path)` | `pygit2_repo.py:227` | `SubmoduleOps` |
| `_submodule_diff_hunk(old_oid, new_oid)` | `pygit2_repo.py:249` | `SubmoduleOps` |

Kept as plain module-level functions (no class wrapping) since they are pure and stateless.

## `repository.py` — composite class

```python
# git_gui/infrastructure/pygit2/repository.py
from __future__ import annotations
import pygit2

from git_gui.infrastructure.commit_ops_cli import CommitOpsCli
from git_gui.infrastructure.submodule_cli import SubmoduleCli
from git_gui.infrastructure.pygit2.branch_ops import BranchOps
from git_gui.infrastructure.pygit2.commit_ops import CommitOps
from git_gui.infrastructure.pygit2.diff_ops import DiffOps
from git_gui.infrastructure.pygit2.merge_rebase_ops import MergeRebaseOps
from git_gui.infrastructure.pygit2.remote_ops import RemoteOps
from git_gui.infrastructure.pygit2.repo_state_ops import RepoStateOps
from git_gui.infrastructure.pygit2.stage_ops import StageOps
from git_gui.infrastructure.pygit2.stash_ops import StashOps
from git_gui.infrastructure.pygit2.submodule_ops import SubmoduleOps
from git_gui.infrastructure.pygit2.tag_ops import TagOps


class Pygit2Repository(
    BranchOps,
    CommitOps,
    DiffOps,
    StageOps,
    TagOps,
    StashOps,
    MergeRebaseOps,
    RemoteOps,
    SubmoduleOps,
    RepoStateOps,
):
    """Composite pygit2 adapter. Every method lives on one of the mixins."""

    def __init__(self, path: str) -> None:
        self._repo = pygit2.Repository(path)
        self._commit_ops_cli = CommitOpsCli(self._repo, self._git_env)
        self._submodule_cli = SubmoduleCli(path)
```

No other statements. The constructor keeps the exact behavior of today's `__init__` (currently at `pygit2_repo.py:260` — read it before implementing to ensure parity, including any path resolution / gitdir handling).

## `__init__.py`

```python
# git_gui/infrastructure/pygit2/__init__.py
from git_gui.infrastructure.pygit2.repository import Pygit2Repository

__all__ = ["Pygit2Repository"]
```

Single public symbol re-exported at the package root.

## Mixin skeletons (representative examples)

Each mixin follows the same pattern:

```python
# git_gui/infrastructure/pygit2/branch_ops.py
from __future__ import annotations
import pygit2
from git_gui.domain.entities import Branch, LocalBranchInfo


class BranchOps:
    """Branch read and write operations on a pygit2 repository.

    This is a mixin. It is not instantiable on its own — it relies on
    `self._repo` being a `pygit2.Repository` set up by the composite class.
    """
    _repo: pygit2.Repository  # provided by the composite

    def get_branches(self) -> list[Branch]:
        ...  # body moved verbatim from pygit2_repo.py

    # ... remaining branch methods, bodies unchanged
```

Type annotation on `_repo` (without assignment) informs readers and type checkers that the mixin expects the composite to provide this attribute. No runtime behavior change.

## `main.py` change

Single-line edit:

```python
# Before:
from git_gui.infrastructure.pygit2_repo import Pygit2Repository

# After:
from git_gui.infrastructure.pygit2 import Pygit2Repository
```

No other change in `main.py`.

## Error handling

Every method's exception behavior is preserved verbatim. No new try/except, no change to logging, no new error types. If a mechanical move accidentally drops a `try`, the integration tests catch it.

## Testing

**Primary safety net (existing tests, no change):** the full `uv run pytest tests/ -q` suite (currently 497 passing). Every public method is exercised end-to-end through `QueryBus`/`CommandBus`-backed integration tests. If the split breaks any path, the suite fails.

**New structural tests:**

`tests/infrastructure/test_pygit2_package.py`:
- Import smoke: `from git_gui.infrastructure.pygit2 import Pygit2Repository` succeeds.
- MRO check: `Pygit2Repository.__mro__` includes all ten mixin classes by name (`BranchOps`, `CommitOps`, `DiffOps`, `StageOps`, `TagOps`, `StashOps`, `MergeRebaseOps`, `RemoteOps`, `SubmoduleOps`, `RepoStateOps`).
- Composite-discipline check: `[n for n in vars(Pygit2Repository) if not n.startswith("__")]` is empty. No non-dunder attribute is defined directly on the composite — everything comes from a mixin. Locks in the pattern so future drift is caught.

`tests/infrastructure/test_pygit2_ports.py`:
- For every abstract method declared on `IRepositoryReader` and `IRepositoryWriter`, assert that `getattr(Pygit2Repository, name, None)` is not `None` and is callable. Guards against a method accidentally dropped during the extraction.

**Not adding:** per-mixin unit tests. Mixins can't be instantiated alone — they rely on `self._repo`, and introducing dependency-injection constructors would defeat the purpose of choosing mixins over the facade alternative. Behavioral coverage is already complete via integration tests.

## Out of scope

- Splitting `IRepositoryReader` / `IRepositoryWriter` into narrower ports.
- Converting any mixin to a facade-adapter with its own constructor and its own port subset.
- Changing method signatures, return types, docstrings, exception behavior, or any logic.
- Refactoring `CommitOpsCli` or `SubmoduleCli` (already separate files).
- Updating any presentation or application layer code.
- Adding new unit tests for individual mixins.
- Renaming existing helpers or changing their signatures.
- Touching the `repos.json` / `remote_tag_cache.json` storage adapters.
