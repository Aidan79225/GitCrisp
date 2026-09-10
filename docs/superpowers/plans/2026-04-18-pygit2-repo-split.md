# Pygit2Repository Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break `git_gui/infrastructure/pygit2_repo.py` (1,422 LOC, 96 methods on one class) into ten focused mixin modules plus a pure-helpers module, under a new `git_gui/infrastructure/pygit2/` subpackage. Mechanical move — external API unchanged.

**Architecture:** `Pygit2Repository` becomes a composite that inherits from ten mixin classes. Each mixin holds the methods for one concern (branches, commits, diffs, etc.) and accesses `self._repo` provided by the composite's `__init__`. Python's MRO resolves cross-mixin calls such as `self._get_signature()` and `self._run_git(...)` without extra wiring.

**Tech Stack:** Python 3.13, pygit2, pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-18-pygit2-repo-split-design.md`

---

## File Structure (end state)

```
git_gui/infrastructure/pygit2/
├── __init__.py               # re-exports Pygit2Repository
├── repository.py             # composite class — __init__ only
├── branch_ops.py
├── commit_ops.py
├── diff_ops.py
├── stage_ops.py
├── tag_ops.py
├── stash_ops.py
├── merge_rebase_ops.py
├── remote_ops.py
├── submodule_ops.py
├── repo_state_ops.py
└── _helpers.py               # pure module-level functions
```

Deleted: `git_gui/infrastructure/pygit2_repo.py`.
Modified: `main.py` (one import line).
New tests: `tests/infrastructure/test_pygit2_package.py`, `tests/infrastructure/test_pygit2_ports.py`.

---

## Mixin-Extraction Pattern (repeated across Tasks 2–11)

Every mixin extraction task follows the same three-step refactor. Reading this pattern once lets the per-task entries stay short.

**Pattern steps for each extraction:**

1. **Create the mixin file** at `git_gui/infrastructure/pygit2/<name>_ops.py` with this skeleton:

   ```python
   # git_gui/infrastructure/pygit2/<name>_ops.py
   from __future__ import annotations
   import pygit2
   # domain / stdlib / _helpers imports — only what the moved methods need

   class <Name>Ops:
       """<One-line docstring of the concern.>

       Mixin — not instantiable on its own. Relies on `self._repo` set up
       by the composite class.
       """
       _repo: pygit2.Repository  # provided by the composite

       # ── METHODS COPIED VERBATIM from Pygit2Repository ─────────────────
       # Paste each listed method with its full body, docstring, and
       # annotations unchanged. Do not edit any logic.
   ```

2. **Update `Pygit2Repository`'s base list** in `git_gui/infrastructure/pygit2_repo.py`:
   - Add `from git_gui.infrastructure.pygit2.<name>_ops import <Name>Ops` near the top with the other mixin imports.
   - Append `<Name>Ops` to the base-class tuple: `class Pygit2Repository(<...existing mixins>, <Name>Ops):`.
   - For Task 2 (first extraction) the class declaration transitions from `class Pygit2Repository:` to `class Pygit2Repository(StashOps):`.

3. **Delete the moved method bodies** from `Pygit2Repository` in `pygit2_repo.py`. Do NOT delete any method that is not in the task's "Methods to move" list. Leave `__init__`, helpers owned by other concerns, and as-yet-unextracted methods alone.

**Verification each time:**
- Run `uv run pytest tests/ -q`.
- Expected: **497 passed, 0 failed** (baseline). A regression means either (a) a method was partially deleted, (b) a private helper was orphaned, or (c) an import is missing in the new mixin file.

**Method-body copying discipline:**
- Copy bodies via `Read` + `Edit`. Do not retype. Do not reformat.
- Docstrings, type hints, and inline comments: unchanged.
- If a body references `self._some_helper` and `_some_helper` lives on a not-yet-extracted concern, the call still works because `_some_helper` is still defined on `Pygit2Repository` at that moment.

**Imports each mixin needs (per task, explicit lists below).** The `pygit2` import is always present. Domain entity imports vary per mixin. `_helpers` imports only what the mixin references.

---

## Task 1: Scaffold subpackage + move pure helpers to `_helpers.py`

Set up the new `pygit2/` subpackage with an empty `__init__.py` and migrate all module-level pure helpers out of `pygit2_repo.py` into `_helpers.py`. After this task, `pygit2_repo.py` imports its pure helpers from the new module but still contains the entire `Pygit2Repository` class.

**Files:**
- Create: `git_gui/infrastructure/pygit2/__init__.py`
- Create: `git_gui/infrastructure/pygit2/_helpers.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Create empty `__init__.py`**

```bash
# Use the Write tool with empty content
```

Write `git_gui/infrastructure/pygit2/__init__.py` with the single line:

```python
# git_gui/infrastructure/pygit2/__init__.py
```

(Will be updated in Task 12 to re-export `Pygit2Repository`.)

- [ ] **Step 2: Read the pure-helper block in `pygit2_repo.py`**

Open `git_gui/infrastructure/pygit2_repo.py` and locate these module-level functions (rough line anchors — confirm with Grep):

- `_map_statuses(flags)` (≈L33)
- `_commit_to_entity(commit)` (≈L42)
- `_diff_to_hunks(patch)` (≈L53)
- `_synthesise_untracked_hunk(workdir, path)` (≈L65)
- `_synthesise_conflict_hunk(workdir, path)` (≈L94)
- `_resolve_gitdir(path)` (≈L139)
- `_parse_gitmodules_paths(workdir)` (≈L206)
- `_read_submodule_head_oid(parent_workdir, sub_path)` (≈L227)
- `_submodule_diff_hunk(old_oid, new_oid)` (≈L249)

All are pure (no `self`, no shared state). Capture the full text of each one, including imports referenced inside the bodies.

- [ ] **Step 3: Create `_helpers.py` with the nine functions**

Write `git_gui/infrastructure/pygit2/_helpers.py`:

```python
# git_gui/infrastructure/pygit2/_helpers.py
"""Pure helpers for the pygit2 adapter family. No pygit2.Repository instance
state, no shared mutable state — these are free functions that the mixins
call during diff synthesis, submodule detection, and entity conversion."""
from __future__ import annotations
# ... (imports required by the function bodies — e.g. from pygit2 import *,
#      from git_gui.domain.entities import *, os, pathlib, etc.)

# Paste the nine functions here VERBATIM, in the order listed in Task 1 Step 2.
```

Include every import the function bodies reference. Preserve docstrings and inline comments. Do not edit any body.

- [ ] **Step 4: Replace the inline bodies in `pygit2_repo.py` with imports**

At the top of `git_gui/infrastructure/pygit2_repo.py`, add:

```python
from git_gui.infrastructure.pygit2._helpers import (
    _map_statuses,
    _commit_to_entity,
    _diff_to_hunks,
    _synthesise_untracked_hunk,
    _synthesise_conflict_hunk,
    _resolve_gitdir,
    _parse_gitmodules_paths,
    _read_submodule_head_oid,
    _submodule_diff_hunk,
)
```

Delete the nine function definitions from `pygit2_repo.py` (only the ones just moved — leave `class Pygit2Repository` and everything below it intact).

- [ ] **Step 5: Run the test suite**

Run: `uv run pytest tests/ -q`
Expected: **497 passed**. If anything fails, the helper move missed an import or a function body.

- [ ] **Step 6: Commit**

```bash
git add git_gui/infrastructure/pygit2/__init__.py git_gui/infrastructure/pygit2/_helpers.py git_gui/infrastructure/pygit2_repo.py
git commit -m "refactor(pygit2): extract pure helpers into pygit2._helpers"
```

---

## Task 2: Extract `StashOps` mixin

Smallest concern, no cross-dependencies. Good sanity check for the extraction pattern.

**Files:**
- Create: `git_gui/infrastructure/pygit2/stash_ops.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

**Methods to move (verbatim, with full bodies):**
- `get_stashes(self) -> list[Stash]` (≈L418)
- `stash(self, message: str) -> None` (≈L1286)
- `pop_stash(self, index: int) -> None` (≈L1290)
- `apply_stash(self, index: int) -> None` (≈L1293)
- `drop_stash(self, index: int) -> None` (≈L1296)

**Imports needed in `stash_ops.py`:**
```python
from __future__ import annotations
import pygit2
from git_gui.domain.entities import Stash
```

(No `_helpers` imports — stash methods use `self._repo` and `self._get_signature` only.)

- [ ] **Step 1: Create `stash_ops.py`** following the Mixin-Extraction Pattern.

- [ ] **Step 2: Add `StashOps` to Pygit2Repository's bases.** Declaration becomes `class Pygit2Repository(StashOps):`.

- [ ] **Step 3: Delete the five method bodies** from `Pygit2Repository`.

- [ ] **Step 4: Run tests.** `uv run pytest tests/ -q` → 497 passed.

- [ ] **Step 5: Commit.**

```bash
git add git_gui/infrastructure/pygit2/stash_ops.py git_gui/infrastructure/pygit2_repo.py
git commit -m "refactor(pygit2): extract StashOps mixin"
```

---

## Task 3: Extract `TagOps` mixin

**Files:**
- Create: `git_gui/infrastructure/pygit2/tag_ops.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

**Methods to move:**
- `get_tags(self) -> list[Tag]` (≈L614)
- `get_remote_tags(self, remote: str) -> list[str]` (≈L648)
- `create_tag(self, name, oid, message)` (≈L1269)
- `delete_tag(self, name)` (≈L1277)
- `push_tag(self, remote, name)` (≈L1280)
- `delete_remote_tag(self, remote, name)` (≈L1283)

**Imports needed:**
```python
from __future__ import annotations
import pygit2
from git_gui.domain.entities import Tag
```

Methods reference `self._run_git(...)` and `self._get_signature()` — those remain on `Pygit2Repository` at this point and will resolve via `self.` either directly or via MRO in later tasks.

- [ ] Steps follow the Mixin-Extraction Pattern.

- [ ] **Commit:** `refactor(pygit2): extract TagOps mixin`

---

## Task 4: Extract `BranchOps` mixin

**Files:**
- Create: `git_gui/infrastructure/pygit2/branch_ops.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

**Methods to move:**
- `get_branches(self) -> list[Branch]` (≈L390)
- `list_local_branches_with_upstream(self) -> list[LocalBranchInfo]` (≈L1387)
- `create_branch(self, name, from_oid)` (≈L1002)
- `checkout(self, branch)` (≈L1007)
- `checkout_commit(self, oid)` (≈L1011)
- `checkout_remote_branch(self, remote_branch)` (≈L1016)
- `delete_branch(self, name)` (≈L1026)
- `rename_branch(self, old_name, new_name)` (≈L1416)
- `set_branch_upstream(self, name, upstream)` (≈L1407)
- `unset_branch_upstream(self, name)` (≈L1412)
- `reset_branch_to_ref(self, branch, ref)` (≈L1419)

**Imports needed:**
```python
from __future__ import annotations
import pygit2
from git_gui.domain.entities import Branch, LocalBranchInfo
```

- [ ] Steps follow the Mixin-Extraction Pattern.

- [ ] **Commit:** `refactor(pygit2): extract BranchOps mixin`

---

## Task 5: Extract `RemoteOps` mixin (owns `_run_git`)

This mixin is the home of the shared `_run_git(*args)` helper. Moving `_run_git` with `RemoteOps` means later mixins' calls to `self._run_git(...)` resolve via MRO.

**Files:**
- Create: `git_gui/infrastructure/pygit2/remote_ops.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

**Methods to move:**
- `list_remotes(self) -> list[Remote]` (≈L1301)
- `add_remote(self, name, url)` (≈L1308)
- `remove_remote(self, name)` (≈L1311)
- `rename_remote(self, old_name, new_name)` (≈L1314)
- `set_remote_url(self, name, url)` (≈L1317)
- `push(self, remote, branch)` (≈L1244)
- `force_push(self, remote, branch)` (≈L1247)
- `pull(self, remote, branch)` (≈L1250)
- `fetch(self, remote)` (≈L1253)
- `fetch_all_prune(self)` (≈L1256)
- `_run_git(self, *args)` — shared helper (≈L1259)

**Imports needed:**
```python
from __future__ import annotations
import subprocess
import pygit2
from git_gui.domain.entities import Remote
```

Note: `_run_git` references `self._git_env`, which is still on `Pygit2Repository` at this stage (moves to `RepoStateOps` in Task 6). Works via `self.` lookup.

- [ ] Steps follow the Mixin-Extraction Pattern.

- [ ] **Commit:** `refactor(pygit2): extract RemoteOps mixin (with _run_git)`

---

## Task 6: Extract `RepoStateOps` mixin (owns `_git_env`)

Repo-level state queries + the `_git_env` property used by every subprocess call. After this task, `_git_env` lives on `RepoStateOps`; other mixins continue to call `self._git_env` which resolves via MRO.

**Files:**
- Create: `git_gui/infrastructure/pygit2/repo_state_ops.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

**Methods / property to move:**
- `get_head_oid(self)` (≈L781)
- `repo_state(self) -> RepoStateInfo` (≈L791)
- `get_merge_head(self)` (≈L829)
- `get_merge_msg(self)` (≈L836)
- `has_unresolved_conflicts(self)` (≈L843)
- `_git_env` **property** (≈L298)

**Imports needed:**
```python
from __future__ import annotations
import os
import pygit2
from git_gui.domain.entities import RepoStateInfo
```

**Note:** `_git_env` is defined with `@property`. Copy the `@property` decorator and the full getter body verbatim.

- [ ] Steps follow the Mixin-Extraction Pattern.

- [ ] **Commit:** `refactor(pygit2): extract RepoStateOps mixin (with _git_env)`

---

## Task 7: Extract `StageOps` mixin (owns `_build_hunk_patch`)

Index / staging operations. `_build_hunk_patch` also used by `DiffOps` (Task 10); it moves here and `DiffOps` will call `self._build_hunk_patch(...)`.

**Files:**
- Create: `git_gui/infrastructure/pygit2/stage_ops.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

**Methods to move:**
- `stage(self, paths)` (≈L863)
- `unstage(self, paths)` (≈L876)
- `stage_hunk(self, path, hunk_header)` (≈L893)
- `unstage_hunk(self, path, hunk_header)` (≈L904)
- `discard_file(self, path)` (≈L915)
- `discard_hunk(self, path, hunk_header)` (≈L948)
- `_build_hunk_patch(self, path, hunk_header, staged)` — shared helper (≈L959)

**Imports needed:**
```python
from __future__ import annotations
import pygit2
from git_gui.infrastructure.pygit2._helpers import _diff_to_hunks
```

(Plus any other stdlib modules referenced by the bodies — `subprocess` if `git apply` shells out, `os` if filesystem operations.)

- [ ] Steps follow the Mixin-Extraction Pattern.

- [ ] **Commit:** `refactor(pygit2): extract StageOps mixin (with _build_hunk_patch)`

---

## Task 8: Extract `CommitOps` mixin (owns `_get_signature`)

Commit reads, commit writes, cherry-pick, revert, reset. Owns `_get_signature` used by many mixins.

**Files:**
- Create: `git_gui/infrastructure/pygit2/commit_ops.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

**Methods to move:**
- `get_commits(self, limit, skip, extra_tips)` (≈L314)
- `get_commit(self, oid)` (≈L351)
- `get_commit_range(self, head_oid, base_oid)` (≈L357)
- `get_commit_files(self, oid)` (≈L436)
- `get_commit_diff_map(self, oid)` (≈L494)
- `get_commit_stats(self, since, until)` (≈L676)
- `is_ancestor(self, ancestor_oid, descendant_oid)` (≈L786)
- `commit(self, message)` (≈L987)
- `reset_to(self, oid, mode)` (≈L1219)
- `cherry_pick(self, oid)` (≈L1209)
- `revert_commit(self, oid)` (≈L1214)
- `cherry_pick_abort(self)` (≈L1227)
- `cherry_pick_continue(self)` (≈L1230)
- `revert_abort(self)` (≈L1233)
- `revert_continue(self)` (≈L1236)
- `_get_signature(self)` — shared helper (≈L855)

**Imports needed:**
```python
from __future__ import annotations
import pygit2
from git_gui.domain.entities import Commit, CommitStat, FileStatus
from git_gui.infrastructure.pygit2._helpers import _commit_to_entity, _diff_to_hunks
```

**Note:** `cherry_pick`, `revert_commit`, and the `*_abort`/`*_continue` variants call `self._commit_ops_cli.<method>(...)`. `self._commit_ops_cli` is constructed in `Pygit2Repository.__init__` and remains available.

- [ ] Steps follow the Mixin-Extraction Pattern.

- [ ] **Commit:** `refactor(pygit2): extract CommitOps mixin (with _get_signature)`

---

## Task 9: Extract `MergeRebaseOps` mixin

Merge, rebase, interactive rebase, abort/continue for both, plus their internal helpers.

**Files:**
- Create: `git_gui/infrastructure/pygit2/merge_rebase_ops.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

**Methods to move:**
- `merge(self, branch, strategy, message)` (≈L1029)
- `merge_commit(self, oid, strategy, message)` (≈L1037)
- `merge_analysis(self, oid)` (≈L1042)
- `_merge_oid(self, target_oid, label, strategy, message)` (≈L1049)
- `rebase(self, branch)` (≈L1091)
- `rebase_onto_commit(self, oid)` (≈L1095)
- `interactive_rebase(self, target_oid, entries)` (≈L1141)
- `merge_abort(self)` (≈L1098)
- `rebase_abort(self)` (≈L1101)
- `rebase_continue(self, message)` (≈L1104)
- `_rebase_onto(self, target_oid)` (≈L1239)

**Imports needed:**
```python
from __future__ import annotations
import os
import subprocess
import tempfile
import pygit2
from git_gui.domain.entities import MergeAnalysisResult
from git_gui.infrastructure.pygit2._helpers import _commit_to_entity
```

(Adjust based on actual body references — `tempfile` and `subprocess` are used for temp-file + `GIT_SEQUENCE_EDITOR` injection during interactive rebase.)

- [ ] Steps follow the Mixin-Extraction Pattern.

- [ ] **Commit:** `refactor(pygit2): extract MergeRebaseOps mixin`

---

## Task 10: Extract `DiffOps` mixin

Largest mixin. Owns `_diff_workfile_against_head`. Calls `self._detect_diverged_submodules()` (still on `Pygit2Repository` until Task 11) and `self._build_hunk_patch(...)` (now on `StageOps` from Task 7) via MRO.

**Files:**
- Create: `git_gui/infrastructure/pygit2/diff_ops.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

**Methods to move:**
- `get_file_diff(self, oid, path)` (≈L458)
- `get_working_tree_diff_map(self)` (≈L513)
- `get_staged_diff(self, path)` (≈L595)
- `get_working_tree(self)` (≈L752)
- `is_dirty(self)` (≈L773)
- `_diff_workfile_against_head(self, path)` (≈L583)

**Imports needed:**
```python
from __future__ import annotations
import pygit2
from git_gui.domain.entities import FileStatus, Hunk, WORKING_TREE_OID
from git_gui.infrastructure.pygit2._helpers import (
    _diff_to_hunks,
    _map_statuses,
    _synthesise_untracked_hunk,
    _synthesise_conflict_hunk,
)
```

(Plus `subprocess` if `is_dirty` shells out to `git status --porcelain`.)

- [ ] Steps follow the Mixin-Extraction Pattern.

- [ ] **Commit:** `refactor(pygit2): extract DiffOps mixin`

---

## Task 11: Extract `SubmoduleOps` mixin (final mixin)

**Files:**
- Create: `git_gui/infrastructure/pygit2/submodule_ops.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

**Methods to move:**
- `list_submodules(self) -> list[Submodule]` (≈L1326)
- `add_submodule(self, path, url)` (≈L1376)
- `remove_submodule(self, path)` (≈L1379)
- `set_submodule_url(self, path, url)` (≈L1382)
- `_submodule_cli(self)` — factory (≈L1322)
- `_detect_diverged_submodules(self)` (≈L265)

**Imports needed:**
```python
from __future__ import annotations
import pygit2
from git_gui.domain.entities import Submodule
from git_gui.infrastructure.pygit2._helpers import (
    _resolve_gitdir,
    _parse_gitmodules_paths,
    _read_submodule_head_oid,
    _submodule_diff_hunk,
)
```

(Plus `subprocess` for `git ls-files -s`.)

After this task, `Pygit2Repository` in `pygit2_repo.py` contains only `__init__` plus all ten mixins in its base list.

- [ ] Steps follow the Mixin-Extraction Pattern.

- [ ] **Commit:** `refactor(pygit2): extract SubmoduleOps mixin`

---

## Task 12: Relocate composite to `repository.py`, update imports, delete old file

`pygit2_repo.py` now contains just `__init__` + the base-list declaration + the import block for all ten mixins. Move it into the subpackage and delete the old location.

**Files:**
- Create: `git_gui/infrastructure/pygit2/repository.py`
- Modify: `git_gui/infrastructure/pygit2/__init__.py`
- Delete: `git_gui/infrastructure/pygit2_repo.py`
- Modify: `main.py`

- [ ] **Step 1a: Read the current `__init__` body from `pygit2_repo.py`**

At this point `pygit2_repo.py` contains only `class Pygit2Repository(...ten mixins...):` followed by the `__init__` method. Read that file and capture the exact `__init__` body verbatim (including any path resolution, gitlink handling via `_resolve_gitdir`, `CommitOpsCli` / `SubmoduleCli` construction, or other setup).

- [ ] **Step 1b: Write `git_gui/infrastructure/pygit2/repository.py`**

Use this skeleton, replacing the `__init__` body with the one captured in Step 1a:

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
    """Composite pygit2 adapter. Every public method lives on one of the
    mixin base classes; this class provides only construction."""

    def __init__(self, path: str) -> None:
        # <paste the exact __init__ body captured in Step 1a>
        ...
```

Also add any additional imports the `__init__` body references (e.g., `_resolve_gitdir` from `._helpers`).

- [ ] **Step 2: Update `__init__.py` to re-export**

Overwrite `git_gui/infrastructure/pygit2/__init__.py` with:

```python
# git_gui/infrastructure/pygit2/__init__.py
from git_gui.infrastructure.pygit2.repository import Pygit2Repository

__all__ = ["Pygit2Repository"]
```

- [ ] **Step 3: Delete `git_gui/infrastructure/pygit2_repo.py`**

Run: `git rm git_gui/infrastructure/pygit2_repo.py`

This removes the file from both the working tree and the index in one go — no separate `git add` needed for the deletion in Step 6.

- [ ] **Step 4: Update `main.py` import**

In `main.py`, replace the line:

```python
from git_gui.infrastructure.pygit2_repo import Pygit2Repository
```

With:

```python
from git_gui.infrastructure.pygit2 import Pygit2Repository
```

- [ ] **Step 5: Run the suite**

Run: `uv run pytest tests/ -q`
Expected: **497 passed**.

If there is an `ImportError: No module named git_gui.infrastructure.pygit2_repo`, some test or module still imports the old path. Grep for it and update to `git_gui.infrastructure.pygit2`.

- [ ] **Step 6: Commit**

```bash
git add git_gui/infrastructure/pygit2/repository.py git_gui/infrastructure/pygit2/__init__.py main.py
# The legacy pygit2_repo.py deletion is already staged by `git rm` in Step 3.
git commit -m "refactor(pygit2): relocate composite to subpackage, remove legacy module"
```

---

## Task 13: Add structural tests

Two tests that guard the new layout against future drift.

**Files:**
- Create: `tests/infrastructure/__init__.py` (if the directory doesn't exist yet — check first)
- Create: `tests/infrastructure/test_pygit2_package.py`
- Create: `tests/infrastructure/test_pygit2_ports.py`

- [ ] **Step 1: Ensure `tests/infrastructure/` exists as a package**

Check: `ls tests/infrastructure/__init__.py`. If missing, create it (empty file).

- [ ] **Step 2: Write `tests/infrastructure/test_pygit2_package.py`**

```python
"""Structural tests for the git_gui.infrastructure.pygit2 subpackage.

Locks in the mixin-composite layout so future drift is caught:
- Pygit2Repository is importable from the package root.
- Its MRO includes every declared mixin.
- No non-dunder attribute is defined directly on the composite class —
  every public method must come from a mixin.
"""
from __future__ import annotations


def test_pygit2_repository_is_importable_from_package_root():
    from git_gui.infrastructure.pygit2 import Pygit2Repository
    assert Pygit2Repository is not None


def test_pygit2_repository_mro_includes_all_mixins():
    from git_gui.infrastructure.pygit2 import Pygit2Repository
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

    mro = Pygit2Repository.__mro__
    expected = {
        BranchOps, CommitOps, DiffOps, MergeRebaseOps, RemoteOps,
        RepoStateOps, StageOps, StashOps, SubmoduleOps, TagOps,
    }
    missing = expected - set(mro)
    assert not missing, f"Pygit2Repository MRO missing mixins: {missing}"


def test_pygit2_repository_composite_defines_no_own_public_attrs():
    """The composite must define only dunders (__init__, __module__, etc.)
    directly. All public behavior comes from mixins. This locks in the
    split pattern — adding a method on the composite would violate it."""
    from git_gui.infrastructure.pygit2 import Pygit2Repository

    own_non_dunders = [
        name for name in vars(Pygit2Repository) if not name.startswith("__")
    ]
    assert own_non_dunders == [], (
        f"Pygit2Repository should not define methods directly; "
        f"move them to the appropriate mixin. Found: {own_non_dunders}"
    )
```

- [ ] **Step 3: Write `tests/infrastructure/test_pygit2_ports.py`**

```python
"""Port-coverage test for Pygit2Repository.

Every abstract method declared on IRepositoryReader and IRepositoryWriter
must be resolvable on Pygit2Repository and callable. Guards against a
method accidentally dropped during the mixin extraction."""
from __future__ import annotations
import inspect

from git_gui.domain.ports import IRepositoryReader, IRepositoryWriter
from git_gui.infrastructure.pygit2 import Pygit2Repository


def _abstract_method_names(port) -> list[str]:
    return [
        name for name, obj in inspect.getmembers(port, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]


def test_pygit2_repository_implements_every_reader_method():
    for name in _abstract_method_names(IRepositoryReader):
        impl = getattr(Pygit2Repository, name, None)
        assert impl is not None, f"Pygit2Repository missing reader method: {name}"
        assert callable(impl), f"Pygit2Repository.{name} is not callable"


def test_pygit2_repository_implements_every_writer_method():
    for name in _abstract_method_names(IRepositoryWriter):
        impl = getattr(Pygit2Repository, name, None)
        assert impl is not None, f"Pygit2Repository missing writer method: {name}"
        assert callable(impl), f"Pygit2Repository.{name} is not callable"
```

- [ ] **Step 4: Run the new tests**

Run: `uv run pytest tests/infrastructure/ -v`
Expected: **5 passed** (3 from `test_pygit2_package.py` + 2 from `test_pygit2_ports.py`).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -q`
Expected: **502 passed** (497 baseline + 5 new structural tests).

- [ ] **Step 6: Commit**

```bash
git add tests/infrastructure/
git commit -m "test(pygit2): add structural guards for the mixin-composite layout"
```

---

## Done

After Task 13 the split is complete. Final state:

- `git_gui/infrastructure/pygit2/` contains the composite class + 10 mixins + pure helpers (≤ 330 LOC per file).
- `git_gui/infrastructure/pygit2_repo.py` no longer exists.
- `main.py` imports from the new subpackage.
- 502 tests pass (497 existing + 5 structural guards).
- Zero changes to domain, application, presentation, or external behavior.
