# Worktree Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-class `git worktree` support to GitCrisp — list, add, remove, lock/unlock — with sidebar nesting under the parent repo, a Tower-style `+` badge on worktree-owning branches, smart-checkout auto-switch on "already checked out" errors, and a two-stage remove flow that surfaces dirty/locked state before forcing.

**Architecture:** New `Worktree` domain entity. Two new query and four new command classes. New pygit2 mixin `WorktreeOps` for read + lock + add. New subprocess wrapper `WorktreeCli` for remove (pygit2 lacks proper directory cleanup). Two new MD3 dialogs (Add Worktree, Manage Worktrees). `RepoListWidget` extended to nest worktrees as QTreeView children under the active repo row. Smart-checkout implemented as a thin service that wraps the existing `Checkout` command. `RepoChangeDetector` watch list extended to include `.git/worktrees/`.

**Tech Stack:** Python 3.13, PySide6 (Qt), pygit2, pytest + pytest-qt. All Python commands run via `uv run`.

**Spec:** `docs/superpowers/specs/2026-05-21-worktree-support-design.md`

---

## File Structure

**New files:**
- `git_gui/infrastructure/worktree_cli.py` — `WorktreeCli` subprocess wrapper + structured error types
- `git_gui/infrastructure/pygit2/worktree_ops.py` — `WorktreeOps` mixin
- `git_gui/presentation/dialogs/add_worktree_dialog.py` — `AddWorktreeDialog`
- `git_gui/presentation/dialogs/worktrees_dialog.py` — `WorktreesDialog` (manage list)
- `git_gui/presentation/services/smart_checkout.py` — `SmartCheckout` wrapper
- `tests/infrastructure/test_worktree_cli.py`
- `tests/infrastructure/pygit2/test_worktree_ops.py`
- `tests/application/test_worktree_use_cases.py`
- `tests/presentation/dialogs/test_add_worktree_dialog.py`
- `tests/presentation/dialogs/test_worktrees_dialog.py`
- `tests/presentation/services/test_smart_checkout.py`
- `tests/presentation/widgets/test_repo_list_worktrees.py`
- `tests/presentation/widgets/test_sidebar_worktree_badge.py`

**Modified files:**
- `git_gui/domain/entities.py` — add `Worktree` dataclass
- `git_gui/domain/ports.py` — extend `IRepositoryReader` and `IRepositoryWriter` protocols
- `git_gui/application/queries.py` — `ListWorktrees`, `FindWorktreeForBranch`
- `git_gui/application/commands.py` — `AddWorktree`, `RemoveWorktree`, `LockWorktree`, `UnlockWorktree`
- `git_gui/infrastructure/pygit2/repository.py` — include `WorktreeOps` in the composite
- `git_gui/infrastructure/pygit2/__init__.py` — re-export if any (verify in step)
- `git_gui/presentation/bus.py` — register new commands/queries on `QueryBus` / `CommandBus`
- `git_gui/presentation/services/repo_change_detector.py` — extend watch list with `.git/worktrees/`
- `git_gui/presentation/widgets/repo_list.py` — render worktree child rows under the active-repo row
- `git_gui/presentation/widgets/sidebar.py` — render `+` badge on worktree-owning branches; add "Checkout in New Worktree…" context menu item
- `git_gui/presentation/widgets/graph.py` — add "Checkout in New Worktree…" to branch-ref context menu
- `git_gui/presentation/dialogs/branches_dialog.py` — render `+` badge column; add "Checkout in New Worktree…" button
- `git_gui/presentation/menus/git_menu.py` — add "Worktrees…" action
- `git_gui/presentation/main_window/main_window.py` — wire signals from new dialogs and from repo_list worktree rows; instantiate `SmartCheckout`
- `git_gui/presentation/main_window/repo_lifecycle.py` — fetch worktree list on `_on_repo_ready` and pass to `_repo_list`; route smart-checkout switches through `_switch_repo`
- `tests/conftest.py` — verify existing `repo_path` fixture works for worktree tests (may need a multi-worktree helper)
- `README.md` — document the new feature (only at the end, in the rollout task)

**Not touched:** theme tokens, QSS templates, logger setup, packaging.

---

## Conventions Reminder (read before starting)

- **Python execution:** ALWAYS `uv run` — never bare `python` or `pytest`. Example: `uv run pytest tests/...`.
- **Architecture:** Clean Architecture is enforced. Dependencies point inward: presentation → application → domain ← infrastructure. Never import presentation or infrastructure modules from domain or application code.
- **Theming:** All colors via `presentation/theme/tokens.py` role tokens (`primary`, `on_surface`, `surface`, `outline`, `error_container`, `secondary_container`, `tertiary`). No hard-coded hex. Use `get_theme_manager().current.colors.as_qcolor(<role>)`.
- **Commits:** small, frequent. Each task ends with a commit. Use `rtk git add <files>` and `rtk git commit -m "..."` (the `rtk` prefix is project convention — see `CLAUDE.md`).
- **Menu tests:** when you need to assert a `QMenu` would have shown an item, use the no-exec `QMenu` subclass pattern from commit `faa45a3` (search for it in existing tests if needed).
- **Signal tests:** prefer `qtbot.waitSignal` over manual sleep loops (see commit `8a47ac2` for the macOS-stable pattern).

---

## Task 1: `Worktree` domain entity

**Files:**
- Modify: `git_gui/domain/entities.py`
- Create: `tests/domain/test_worktree_entity.py`

- [ ] **Step 1: Write the failing test**

Create `tests/domain/test_worktree_entity.py`:
```python
from __future__ import annotations
from pathlib import Path

from git_gui.domain.entities import Worktree


def test_worktree_is_frozen_dataclass():
    wt = Worktree(
        path=Path("/tmp/repo-feat-x"),
        branch="feat/x",
        head_sha="abc1234",
        is_locked=False,
        lock_reason=None,
        is_bare=False,
        is_main=False,
    )
    assert wt.path == Path("/tmp/repo-feat-x")
    assert wt.branch == "feat/x"
    assert wt.head_sha == "abc1234"
    assert wt.is_locked is False
    assert wt.lock_reason is None
    assert wt.is_bare is False
    assert wt.is_main is False


def test_worktree_supports_detached_head():
    wt = Worktree(
        path=Path("/tmp/repo-detached"),
        branch=None,
        head_sha="deadbeef",
        is_locked=False,
        lock_reason=None,
        is_bare=False,
        is_main=False,
    )
    assert wt.branch is None


def test_worktree_supports_locked_with_reason():
    wt = Worktree(
        path=Path("/tmp/repo-locked"),
        branch="hotfix",
        head_sha="abc",
        is_locked=True,
        lock_reason="rebuilding artifacts overnight",
        is_bare=False,
        is_main=False,
    )
    assert wt.is_locked is True
    assert wt.lock_reason == "rebuilding artifacts overnight"


def test_worktree_is_frozen():
    import dataclasses
    wt = Worktree(
        path=Path("/tmp/r"), branch="main", head_sha="abc",
        is_locked=False, lock_reason=None, is_bare=False, is_main=True,
    )
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        wt.branch = "other"  # type: ignore[misc]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/domain/test_worktree_entity.py -v`
Expected: FAIL with `ImportError` — `Worktree` is not in `git_gui.domain.entities`.

- [ ] **Step 3: Add the `Worktree` dataclass**

Edit `git_gui/domain/entities.py`. Add the `Path` import at the top of the file:
```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal
```

Then at the bottom of the file (after `MergeAnalysisResult`), add:
```python
@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str | None        # None when HEAD is detached
    head_sha: str
    is_locked: bool
    lock_reason: str | None   # None when not locked or no reason given
    is_bare: bool
    is_main: bool             # True for the primary worktree
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/domain/test_worktree_entity.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
rtk git add git_gui/domain/entities.py tests/domain/test_worktree_entity.py
rtk git commit -m "domain: add Worktree entity"
```

---

## Task 2: Extend domain ports

`IRepositoryReader` and `IRepositoryWriter` are runtime-checkable Protocols. Adding methods to a Protocol does not break existing implementations unless we runtime-check them strictly — pygit2 mixins will satisfy the new methods once Task 3-5 land. We add the protocol shape now so the application layer has something to depend on.

**Files:**
- Modify: `git_gui/domain/ports.py`

- [ ] **Step 1: Add reader port methods**

Edit `git_gui/domain/ports.py`. At the top of the file, add `Worktree` to the import from entities:
```python
from git_gui.domain.entities import Branch, Commit, CommitStat, FileStatus, Hunk, LocalBranchInfo, MergeAnalysisResult, MergeStrategy, Remote, RepoStateInfo, ResetMode, Stash, Submodule, Tag, Worktree
```

Also add `Path` to the top imports:
```python
from pathlib import Path
```

Inside `class IRepositoryReader(Protocol):`, append at the end (after `get_commit_range`):
```python
    def list_worktrees(self) -> list[Worktree]: ...
    def find_worktree_for_branch(self, branch: str) -> Worktree | None: ...
```

- [ ] **Step 2: Add writer port methods**

Inside `class IRepositoryWriter(Protocol):`, append at the end (after `revert_continue`):
```python
    def add_worktree(
        self,
        path: Path,
        branch: str,
        *,
        create_branch: bool,
        base_ref: str | None,
    ) -> Worktree: ...
    def remove_worktree(self, path: Path, *, force: bool) -> None: ...
    def lock_worktree(self, path: Path, *, reason: str | None) -> None: ...
    def unlock_worktree(self, path: Path) -> None: ...
```

- [ ] **Step 3: Verify no test regressions**

Run: `uv run pytest tests/domain/ -v`
Expected: previous domain tests still pass; entity test still passes.

- [ ] **Step 4: Commit**

```bash
rtk git add git_gui/domain/ports.py
rtk git commit -m "domain: extend reader/writer ports with worktree methods"
```

---

## Task 3: `WorktreeCli` subprocess wrapper

This wraps `git worktree remove [--force]`. pygit2 has `Worktree.prune()` but not a "remove with directory cleanup" — same situation as submodule removal. Mirrors the pattern in `git_gui/infrastructure/submodule_cli.py`. Parses stderr for `is dirty` / `is locked` and raises typed errors so the UI can branch on them.

**Files:**
- Create: `git_gui/infrastructure/worktree_cli.py`
- Create: `tests/infrastructure/test_worktree_cli.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_worktree_cli.py`:
```python
"""Tests for the git-worktree-remove subprocess wrapper.

Uses real pygit2 fixtures (no subprocess mocking). Builds a small repo with
a real worktree, then exercises the wrapper's remove paths.
"""
from __future__ import annotations
from pathlib import Path
import subprocess

import pytest
import pygit2

from git_gui.infrastructure.worktree_cli import (
    WorktreeCli,
    WorktreeDirtyError,
    WorktreeLockedError,
    WorktreeCommandError,
)


@pytest.fixture
def repo_with_worktree(tmp_path):
    """Create a main repo + a sibling worktree on a feature branch."""
    main = tmp_path / "main"
    repo = pygit2.init_repository(str(main))
    repo.config["user.name"] = "T"
    repo.config["user.email"] = "t@e.com"
    sig = pygit2.Signature("T", "t@e.com")
    (main / "a.txt").write_text("hello\n")
    repo.index.add("a.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("refs/heads/master", sig, sig, "init", tree, [])
    # Make a feature branch
    head_oid = repo.head.target
    repo.references.create("refs/heads/feat", head_oid)
    # Use subprocess to create the worktree — pygit2 add_worktree
    # requires a ref object and works, but we want to mirror the user's
    # path here. Equivalent.
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", str(wt_path), "feat"],
        check=True, capture_output=True,
    )
    return main, wt_path


def test_remove_clean_worktree_succeeds(repo_with_worktree):
    main, wt = repo_with_worktree
    cli = WorktreeCli(str(main))
    cli.remove(str(wt), force=False)
    assert not wt.exists()


def test_remove_dirty_worktree_without_force_raises_dirty(repo_with_worktree):
    main, wt = repo_with_worktree
    # Make the worktree dirty.
    (wt / "a.txt").write_text("changed\n")
    cli = WorktreeCli(str(main))
    with pytest.raises(WorktreeDirtyError):
        cli.remove(str(wt), force=False)
    # Worktree still exists.
    assert wt.exists()


def test_remove_dirty_worktree_with_force_succeeds(repo_with_worktree):
    main, wt = repo_with_worktree
    (wt / "a.txt").write_text("changed\n")
    cli = WorktreeCli(str(main))
    cli.remove(str(wt), force=True)
    assert not wt.exists()


def test_remove_locked_worktree_without_force_raises_locked(repo_with_worktree):
    main, wt = repo_with_worktree
    # Lock the worktree.
    subprocess.run(
        ["git", "-C", str(main), "worktree", "lock", str(wt)],
        check=True, capture_output=True,
    )
    cli = WorktreeCli(str(main))
    with pytest.raises(WorktreeLockedError):
        cli.remove(str(wt), force=False)


def test_remove_unknown_path_raises_generic(repo_with_worktree, tmp_path):
    main, _ = repo_with_worktree
    cli = WorktreeCli(str(main))
    bogus = tmp_path / "does-not-exist"
    with pytest.raises(WorktreeCommandError):
        cli.remove(str(bogus), force=False)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/infrastructure/test_worktree_cli.py -v`
Expected: FAIL with `ImportError` — `worktree_cli` module not found.

- [ ] **Step 3: Implement the wrapper**

Create `git_gui/infrastructure/worktree_cli.py`:
```python
from __future__ import annotations
import re
import shutil
import subprocess

from git_gui.resources import subprocess_kwargs


class WorktreeCommandError(Exception):
    """Generic failure from `git worktree ...`."""


class WorktreeDirtyError(WorktreeCommandError):
    """Removal refused because the worktree has uncommitted changes."""


class WorktreeLockedError(WorktreeCommandError):
    """Removal refused because the worktree is locked."""


_DIRTY_RE = re.compile(r"\b(is dirty|contains modified or untracked files)\b", re.IGNORECASE)
_LOCKED_RE = re.compile(r"\b(is locked|locked working tree)\b", re.IGNORECASE)


class WorktreeCli:
    """Thin wrapper around `git worktree remove` executed via subprocess.

    pygit2 lacks a "remove worktree with directory cleanup" call, so we
    shell out to the git CLI. The repo's main working directory is used
    as cwd so relative-path resolution matches the user's invocation.
    """

    def __init__(self, repo_workdir: str, git_executable: str = "git") -> None:
        self._cwd = repo_workdir
        self._git = git_executable

    def remove(self, worktree_path: str, *, force: bool) -> None:
        """Remove a worktree. Raises `WorktreeDirtyError` /
        `WorktreeLockedError` / `WorktreeCommandError`."""
        if shutil.which(self._git) is None:
            raise WorktreeCommandError(
                f"`{self._git}` executable not found on PATH"
            )
        args = [self._git, "worktree", "remove"]
        if force:
            args.append("--force")
        args.append(worktree_path)
        try:
            subprocess.run(
                args,
                cwd=self._cwd,
                check=True,
                capture_output=True,
                text=True,
                **subprocess_kwargs(),
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip() or (e.stdout or "").strip() or str(e)
            if _DIRTY_RE.search(stderr):
                raise WorktreeDirtyError(stderr) from e
            if _LOCKED_RE.search(stderr):
                raise WorktreeLockedError(stderr) from e
            raise WorktreeCommandError(stderr) from e
        except FileNotFoundError as e:
            raise WorktreeCommandError(
                f"`{self._git}` executable not found on PATH"
            ) from e
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/infrastructure/test_worktree_cli.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
rtk git add git_gui/infrastructure/worktree_cli.py tests/infrastructure/test_worktree_cli.py
rtk git commit -m "infra(worktree): add WorktreeCli subprocess wrapper with typed errors"
```

---

## Task 4: `WorktreeOps` pygit2 mixin

Implements list / find-for-branch / add / lock / unlock against pygit2. Delegates `remove_worktree` to `WorktreeCli` (Task 3). Lives at `git_gui/infrastructure/pygit2/worktree_ops.py` alongside the existing nine mixins.

pygit2 surfaces worktrees via:
- `repo.list_worktrees()` → list of worktree names (strings)
- `repo.lookup_worktree(name)` → `pygit2.Worktree` object (path, locked state, branch detection)
- `repo.add_worktree(name, path, ref=...)` → creates a worktree

There are some pygit2 idiosyncrasies to handle:
- The "name" used by pygit2 is the worktree's directory name as stored in `.git/worktrees/<name>/`. Not necessarily the branch name.
- A worktree's `branch` must be derived by inspecting its HEAD file or the branch ref it points to (pygit2's Worktree object exposes `path`).
- The main worktree is not returned by `list_worktrees()`. We synthesize it manually (path = `repo.workdir`, branch = current HEAD branch, is_main = True).

**Files:**
- Create: `git_gui/infrastructure/pygit2/worktree_ops.py`
- Create: `tests/infrastructure/pygit2/test_worktree_ops.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/pygit2/test_worktree_ops.py`:
```python
"""WorktreeOps mixin — exercised via Pygit2Repository against real repos."""
from __future__ import annotations
from pathlib import Path
import subprocess

import pytest
import pygit2

from git_gui.infrastructure.pygit2 import Pygit2Repository
from git_gui.infrastructure.worktree_cli import (
    WorktreeDirtyError,
    WorktreeLockedError,
)


@pytest.fixture
def fresh_repo(tmp_path):
    """Empty-ish repo with one commit on master."""
    p = tmp_path / "main"
    p.mkdir()
    repo = pygit2.init_repository(str(p))
    repo.config["user.name"] = "T"
    repo.config["user.email"] = "t@e.com"
    sig = pygit2.Signature("T", "t@e.com")
    (p / "a.txt").write_text("hi\n")
    repo.index.add("a.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("refs/heads/master", sig, sig, "init", tree, [])
    return p


def test_list_worktrees_returns_just_main_when_no_extra(fresh_repo):
    impl = Pygit2Repository(str(fresh_repo))
    wts = impl.list_worktrees()
    assert len(wts) == 1
    main = wts[0]
    assert main.is_main is True
    assert main.path == Path(str(fresh_repo)).resolve()
    assert main.branch == "master"
    assert main.is_locked is False


def test_list_worktrees_includes_added_worktree(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True, capture_output=True,
    )
    impl = Pygit2Repository(str(fresh_repo))
    wts = impl.list_worktrees()
    branches = {wt.branch for wt in wts}
    assert "master" in branches
    assert "feat" in branches
    feat = next(wt for wt in wts if wt.branch == "feat")
    assert feat.is_main is False
    assert feat.path == wt_path.resolve()


def test_add_worktree_creates_new_branch_and_directory(fresh_repo, tmp_path):
    impl = Pygit2Repository(str(fresh_repo))
    target = tmp_path / "wt-new"
    wt = impl.add_worktree(
        target, "feat/new", create_branch=True, base_ref="master",
    )
    assert target.exists()
    assert wt.branch == "feat/new"
    assert wt.is_main is False
    # The branch must now exist in the underlying repo.
    repo = pygit2.Repository(str(fresh_repo))
    assert "refs/heads/feat/new" in [b for b in repo.references]


def test_add_worktree_attaches_existing_branch(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/existing", repo.head.target)
    impl = Pygit2Repository(str(fresh_repo))
    target = tmp_path / "wt-existing"
    wt = impl.add_worktree(
        target, "existing", create_branch=False, base_ref=None,
    )
    assert wt.branch == "existing"


def test_find_worktree_for_branch_returns_match(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add",
         str(tmp_path / "wt-feat"), "feat"],
        check=True, capture_output=True,
    )
    impl = Pygit2Repository(str(fresh_repo))
    wt = impl.find_worktree_for_branch("feat")
    assert wt is not None
    assert wt.branch == "feat"


def test_find_worktree_for_branch_returns_none_when_missing(fresh_repo):
    impl = Pygit2Repository(str(fresh_repo))
    assert impl.find_worktree_for_branch("does-not-exist") is None


def test_lock_and_unlock_round_trip(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True, capture_output=True,
    )
    impl = Pygit2Repository(str(fresh_repo))
    impl.lock_worktree(wt_path, reason="testing")
    wts = impl.list_worktrees()
    feat = next(wt for wt in wts if wt.branch == "feat")
    assert feat.is_locked is True

    impl.unlock_worktree(wt_path)
    wts = impl.list_worktrees()
    feat = next(wt for wt in wts if wt.branch == "feat")
    assert feat.is_locked is False


def test_remove_worktree_clean(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True, capture_output=True,
    )
    impl = Pygit2Repository(str(fresh_repo))
    impl.remove_worktree(wt_path, force=False)
    assert not wt_path.exists()


def test_remove_worktree_dirty_without_force_raises(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True, capture_output=True,
    )
    (wt_path / "a.txt").write_text("changed\n")
    impl = Pygit2Repository(str(fresh_repo))
    with pytest.raises(WorktreeDirtyError):
        impl.remove_worktree(wt_path, force=False)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/infrastructure/pygit2/test_worktree_ops.py -v`
Expected: FAIL with `AttributeError` — `list_worktrees` not found on Pygit2Repository (the mixin isn't wired yet).

- [ ] **Step 3: Implement the mixin**

Create `git_gui/infrastructure/pygit2/worktree_ops.py`:
```python
from __future__ import annotations
import logging
from pathlib import Path

import pygit2

from git_gui.domain.entities import Worktree

logger = logging.getLogger(__name__)


def _read_head_branch(workdir: str) -> tuple[str | None, str]:
    """Return (branch_name_or_None, head_sha) for a worktree at *workdir*.

    Reads `.git` (a file in linked worktrees, a dir in the main worktree)
    and resolves the HEAD ref. On detached HEAD, branch is None and sha is
    the raw object id; on attached HEAD, branch is the short ref name.
    """
    repo = pygit2.Repository(workdir)
    try:
        head = repo.head
    except pygit2.GitError:
        return None, ""
    if repo.head_is_detached:
        return None, str(head.target)
    short = head.shorthand
    return short, str(head.target)


class WorktreeOps:
    """Worktree read/write operations.

    Mixin — not instantiable on its own. Relies on `self._repo` set up
    by the composite class.
    """
    _repo: pygit2.Repository  # provided by the composite

    # ── Reads ────────────────────────────────────────────────────────────

    def list_worktrees(self) -> list[Worktree]:
        result: list[Worktree] = []

        # Main worktree.
        main_workdir = self._repo.workdir or ""
        if main_workdir:
            main_branch, main_sha = _read_head_branch(main_workdir)
            result.append(Worktree(
                path=Path(main_workdir).resolve(),
                branch=main_branch,
                head_sha=main_sha,
                is_locked=False,
                lock_reason=None,
                is_bare=self._repo.is_bare,
                is_main=True,
            ))

        # Linked worktrees.
        try:
            names = list(self._repo.list_worktrees())
        except Exception as e:
            logger.warning("Failed to list linked worktrees: %s", e)
            names = []
        for name in names:
            try:
                wt = self._repo.lookup_worktree(name)
            except Exception as e:
                logger.warning("Failed to look up worktree %r: %s", name, e)
                continue
            try:
                wt_branch, wt_sha = _read_head_branch(wt.path)
            except Exception as e:
                logger.warning("Failed to read HEAD for worktree %r: %s", name, e)
                wt_branch, wt_sha = None, ""
            try:
                is_locked = wt.is_locked
            except AttributeError:
                # Older pygit2 — no is_locked attribute, fall back to file check.
                is_locked = (Path(self._repo.path) / "worktrees" / name / "locked").exists()
            lock_reason = None
            if is_locked:
                locked_file = Path(self._repo.path) / "worktrees" / name / "locked"
                try:
                    lock_reason = locked_file.read_text().strip() or None
                except OSError:
                    lock_reason = None
            result.append(Worktree(
                path=Path(wt.path).resolve(),
                branch=wt_branch,
                head_sha=wt_sha,
                is_locked=bool(is_locked),
                lock_reason=lock_reason,
                is_bare=False,
                is_main=False,
            ))
        return result

    def find_worktree_for_branch(self, branch: str) -> Worktree | None:
        for wt in self.list_worktrees():
            if wt.branch == branch:
                return wt
        return None

    # ── Writes ───────────────────────────────────────────────────────────

    def add_worktree(
        self,
        path: Path,
        branch: str,
        *,
        create_branch: bool,
        base_ref: str | None,
    ) -> Worktree:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if create_branch:
            base = base_ref or "HEAD"
            try:
                base_obj = self._repo.revparse_single(base)
            except Exception as e:
                raise ValueError(f"Base ref not found: {base}") from e
            self._repo.references.create(f"refs/heads/{branch}", base_obj.id)

        ref = self._repo.references.get(f"refs/heads/{branch}")
        if ref is None:
            raise ValueError(f"Branch not found: {branch}")

        # pygit2's name is a directory identifier; use the basename of the
        # target to keep it predictable.
        wt_name = target.name
        self._repo.add_worktree(wt_name, str(target), ref)

        wt_branch, wt_sha = _read_head_branch(str(target))
        return Worktree(
            path=target.resolve(),
            branch=wt_branch,
            head_sha=wt_sha,
            is_locked=False,
            lock_reason=None,
            is_bare=False,
            is_main=False,
        )

    def remove_worktree(self, path: Path, *, force: bool) -> None:
        from git_gui.infrastructure.worktree_cli import WorktreeCli
        cli = WorktreeCli(self._repo.workdir)
        cli.remove(str(path), force=force)

    def lock_worktree(self, path: Path, *, reason: str | None) -> None:
        target = Path(path).resolve()
        name = self._worktree_name_for(target)
        wt = self._repo.lookup_worktree(name)
        # pygit2 ≥ 1.13 exposes lock()/unlock(); older versions need a
        # manual file write. Try the API first.
        try:
            wt.lock()
        except (AttributeError, TypeError):
            (Path(self._repo.path) / "worktrees" / name / "locked").touch()
        if reason is not None:
            (Path(self._repo.path) / "worktrees" / name / "locked").write_text(reason)

    def unlock_worktree(self, path: Path) -> None:
        target = Path(path).resolve()
        name = self._worktree_name_for(target)
        wt = self._repo.lookup_worktree(name)
        try:
            wt.unlock()
        except (AttributeError, TypeError):
            locked = Path(self._repo.path) / "worktrees" / name / "locked"
            if locked.exists():
                locked.unlink()

    # ── Internals ────────────────────────────────────────────────────────

    def _worktree_name_for(self, path: Path) -> str:
        for name in self._repo.list_worktrees():
            wt = self._repo.lookup_worktree(name)
            if Path(wt.path).resolve() == path:
                return name
        raise ValueError(f"No worktree at {path}")
```

- [ ] **Step 4: Wire the mixin into the composite**

Edit `git_gui/infrastructure/pygit2/repository.py`. Add the import:
```python
from git_gui.infrastructure.pygit2.worktree_ops import WorktreeOps
```

Add `WorktreeOps` to the base-class tuple of `Pygit2Repository`:
```python
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
    WorktreeOps,
):
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `uv run pytest tests/infrastructure/pygit2/test_worktree_ops.py -v`
Expected: 9 passed.

Also run the full infra suite to verify nothing else broke:
Run: `uv run pytest tests/infrastructure/ -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
rtk git add git_gui/infrastructure/pygit2/worktree_ops.py git_gui/infrastructure/pygit2/repository.py tests/infrastructure/pygit2/test_worktree_ops.py
rtk git commit -m "infra(worktree): add WorktreeOps mixin + wire into composite"
```

---

## Task 5: Application use cases

Thin command and query wrappers that delegate to the port. Mirrors the structure of `Checkout`, `AddRemote`, etc.

**Files:**
- Modify: `git_gui/application/queries.py`
- Modify: `git_gui/application/commands.py`
- Create: `tests/application/test_worktree_use_cases.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/application/test_worktree_use_cases.py`:
```python
"""Application use cases for worktrees — thin delegation to ports."""
from __future__ import annotations
from pathlib import Path

from git_gui.application.queries import ListWorktrees, FindWorktreeForBranch
from git_gui.application.commands import (
    AddWorktree, RemoveWorktree, LockWorktree, UnlockWorktree,
)
from git_gui.domain.entities import Worktree


class _FakeReader:
    def __init__(self):
        self.list_calls = 0
        self.find_calls: list[str] = []
        self._wts: list[Worktree] = []
        self._find_result: Worktree | None = None

    def list_worktrees(self):
        self.list_calls += 1
        return list(self._wts)

    def find_worktree_for_branch(self, branch):
        self.find_calls.append(branch)
        return self._find_result


class _FakeWriter:
    def __init__(self):
        self.add_calls: list[tuple] = []
        self.remove_calls: list[tuple] = []
        self.lock_calls: list[tuple] = []
        self.unlock_calls: list[Path] = []

    def add_worktree(self, path, branch, *, create_branch, base_ref):
        self.add_calls.append((path, branch, create_branch, base_ref))
        return Worktree(
            path=path, branch=branch, head_sha="x",
            is_locked=False, lock_reason=None, is_bare=False, is_main=False,
        )

    def remove_worktree(self, path, *, force):
        self.remove_calls.append((path, force))

    def lock_worktree(self, path, *, reason):
        self.lock_calls.append((path, reason))

    def unlock_worktree(self, path):
        self.unlock_calls.append(path)


def test_list_worktrees_delegates():
    reader = _FakeReader()
    q = ListWorktrees(reader)  # type: ignore[arg-type]
    q.execute()
    assert reader.list_calls == 1


def test_find_worktree_for_branch_delegates():
    reader = _FakeReader()
    q = FindWorktreeForBranch(reader)  # type: ignore[arg-type]
    q.execute("feat/x")
    assert reader.find_calls == ["feat/x"]


def test_add_worktree_delegates():
    writer = _FakeWriter()
    c = AddWorktree(writer)  # type: ignore[arg-type]
    p = Path("/tmp/x")
    c.execute(p, "feat", create_branch=True, base_ref="master")
    assert writer.add_calls == [(p, "feat", True, "master")]


def test_remove_worktree_delegates():
    writer = _FakeWriter()
    c = RemoveWorktree(writer)  # type: ignore[arg-type]
    p = Path("/tmp/x")
    c.execute(p, force=True)
    assert writer.remove_calls == [(p, True)]


def test_lock_worktree_delegates():
    writer = _FakeWriter()
    c = LockWorktree(writer)  # type: ignore[arg-type]
    p = Path("/tmp/x")
    c.execute(p, reason="busy")
    assert writer.lock_calls == [(p, "busy")]


def test_unlock_worktree_delegates():
    writer = _FakeWriter()
    c = UnlockWorktree(writer)  # type: ignore[arg-type]
    p = Path("/tmp/x")
    c.execute(p)
    assert writer.unlock_calls == [p]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/application/test_worktree_use_cases.py -v`
Expected: FAIL with `ImportError` — use case classes not found.

- [ ] **Step 3: Add the query classes**

Edit `git_gui/application/queries.py`. At the top, add to the entity import:
```python
from git_gui.domain.entities import Branch, Commit, CommitStat, FileStatus, Hunk, LocalBranchInfo, Remote, RepoStateInfo, Stash, Submodule, Tag, MergeAnalysisResult, Worktree
```

At the bottom of the file, append:
```python
class ListWorktrees:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> list[Worktree]:
        return self._reader.list_worktrees()


class FindWorktreeForBranch:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, branch: str) -> Worktree | None:
        return self._reader.find_worktree_for_branch(branch)
```

- [ ] **Step 4: Add the command classes**

Edit `git_gui/application/commands.py`. At the top, add `Path` and `Worktree` imports:
```python
from pathlib import Path
from git_gui.domain.entities import Branch, Commit, MergeStrategy, ResetMode, Worktree
```

At the bottom of the file, append:
```python
class AddWorktree:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(
        self,
        path: Path,
        branch: str,
        *,
        create_branch: bool,
        base_ref: str | None,
    ) -> Worktree:
        return self._writer.add_worktree(
            path, branch, create_branch=create_branch, base_ref=base_ref,
        )


class RemoveWorktree:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: Path, *, force: bool) -> None:
        self._writer.remove_worktree(path, force=force)


class LockWorktree:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: Path, *, reason: str | None) -> None:
        self._writer.lock_worktree(path, reason=reason)


class UnlockWorktree:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: Path) -> None:
        self._writer.unlock_worktree(path)
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `uv run pytest tests/application/test_worktree_use_cases.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
rtk git add git_gui/application/queries.py git_gui/application/commands.py tests/application/test_worktree_use_cases.py
rtk git commit -m "app(worktree): add use cases for list/find/add/remove/lock/unlock"
```

---

## Task 6: Register on the buses

Add the new commands/queries to `QueryBus` and `CommandBus`.

**Files:**
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Extend `QueryBus`**

Edit `git_gui/presentation/bus.py`. Update the `from git_gui.application.queries import (...)` block to add the two new classes:
```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes, GetTags, GetRemoteTags, GetCommitStats,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
    GetCommitDetail, IsDirty, GetHeadOid,
    ListRemotes, ListSubmodules, ListLocalBranchesWithUpstream,
    GetRepoState, IsAncestor, GetMergeAnalysis,
    GetMergeHead, GetMergeMsg, HasUnresolvedConflicts,
    GetCommitDiffMap, GetWorkingTreeDiffMap, GetCommitRange,
    ListWorktrees, FindWorktreeForBranch,
)
```

In `class QueryBus`, append two fields below `get_commit_range`:
```python
    list_worktrees: ListWorktrees
    find_worktree_for_branch: FindWorktreeForBranch
```

In `QueryBus.from_reader`, add the corresponding constructor calls inside the `cls(...)` block:
```python
            list_worktrees=ListWorktrees(reader),
            find_worktree_for_branch=FindWorktreeForBranch(reader),
```

- [ ] **Step 2: Extend `CommandBus`**

In the `from git_gui.application.commands import (...)` block, add:
```python
    AddWorktree, RemoveWorktree, LockWorktree, UnlockWorktree,
```

In `class CommandBus`, append four fields below `revert_continue`:
```python
    add_worktree: AddWorktree
    remove_worktree: RemoveWorktree
    lock_worktree: LockWorktree
    unlock_worktree: UnlockWorktree
```

In `CommandBus.from_writer`, add the corresponding constructor calls:
```python
            add_worktree=AddWorktree(writer),
            remove_worktree=RemoveWorktree(writer),
            lock_worktree=LockWorktree(writer),
            unlock_worktree=UnlockWorktree(writer),
```

- [ ] **Step 3: Verify the application still imports**

Run: `uv run python -c "from git_gui.presentation.bus import QueryBus, CommandBus; print(QueryBus, CommandBus)"`
Expected: prints the two classes; no `ImportError` or `TypeError`.

- [ ] **Step 4: Commit**

```bash
rtk git add git_gui/presentation/bus.py
rtk git commit -m "presentation(bus): register worktree queries and commands"
```

---

## Task 7: `SmartCheckout` service

A thin presentation-layer service that wraps the existing `Checkout` command. On the specific pygit2 error indicating the branch is checked out in another worktree, it looks up the owning worktree and emits a `switch_to_worktree_requested` signal. Otherwise it re-raises so callers see the original error.

The service does NOT depend on QtWidgets — it's a `QObject` so it can carry a `Signal`. Callers (MainWindow) connect the signal to `_switch_repo`.

**Files:**
- Create: `git_gui/presentation/services/smart_checkout.py`
- Create: `tests/presentation/services/test_smart_checkout.py`

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/services/test_smart_checkout.py`:
```python
from __future__ import annotations
from pathlib import Path

import pytest
import pygit2

from git_gui.domain.entities import Worktree
from git_gui.presentation.services.smart_checkout import SmartCheckout


class _FakeCheckout:
    def __init__(self, raise_on=None):
        self._raise = raise_on
        self.calls: list[str] = []
    def execute(self, branch):
        self.calls.append(branch)
        if self._raise is not None:
            raise self._raise


class _FakeFinder:
    def __init__(self, result=None):
        self._result = result
        self.calls: list[str] = []
    def execute(self, branch):
        self.calls.append(branch)
        return self._result


def _wt(path="/tmp/wt", branch="feat"):
    return Worktree(
        path=Path(path), branch=branch, head_sha="x",
        is_locked=False, lock_reason=None, is_bare=False, is_main=False,
    )


def test_normal_checkout_does_not_emit_switch(qtbot):
    checkout = _FakeCheckout()
    finder = _FakeFinder()
    sc = SmartCheckout(checkout, finder)  # type: ignore[arg-type]
    received = []
    sc.switch_to_worktree_requested.connect(received.append)
    sc.execute("feat")
    assert checkout.calls == ["feat"]
    assert received == []


def test_worktree_collision_switches_and_does_not_raise(qtbot):
    err = pygit2.GitError(
        "branch 'feat' already used by worktree at /tmp/wt"
    )
    checkout = _FakeCheckout(raise_on=err)
    finder = _FakeFinder(result=_wt("/tmp/wt", "feat"))
    sc = SmartCheckout(checkout, finder)  # type: ignore[arg-type]
    received: list[str] = []
    sc.switch_to_worktree_requested.connect(received.append)
    sc.execute("feat")  # must NOT raise
    assert received == ["/tmp/wt"]


def test_worktree_collision_no_owning_worktree_reraises(qtbot):
    err = pygit2.GitError(
        "branch 'feat' already used by worktree at /missing"
    )
    checkout = _FakeCheckout(raise_on=err)
    finder = _FakeFinder(result=None)
    sc = SmartCheckout(checkout, finder)  # type: ignore[arg-type]
    with pytest.raises(pygit2.GitError):
        sc.execute("feat")


def test_unrelated_error_propagates(qtbot):
    err = pygit2.GitError("some unrelated failure")
    checkout = _FakeCheckout(raise_on=err)
    finder = _FakeFinder(result=_wt())
    sc = SmartCheckout(checkout, finder)  # type: ignore[arg-type]
    with pytest.raises(pygit2.GitError):
        sc.execute("feat")
    assert finder.calls == []  # collision detection rejected; finder not called
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run pytest tests/presentation/services/test_smart_checkout.py -v`
Expected: FAIL with `ImportError` — module not found.

- [ ] **Step 3: Implement the service**

Create `git_gui/presentation/services/smart_checkout.py`:
```python
"""Smart-checkout: intercept the 'branch is in another worktree' error
and switch to the owning worktree instead of surfacing the error."""
from __future__ import annotations
import re

from PySide6.QtCore import QObject, Signal

_COLLISION_RE = re.compile(
    r"already used by worktree at\s+(.+)$",
    re.IGNORECASE | re.MULTILINE,
)


def _looks_like_worktree_collision(err: Exception) -> bool:
    msg = str(err)
    return bool(_COLLISION_RE.search(msg))


class SmartCheckout(QObject):
    """Wraps the bus's `Checkout` command. On worktree-collision errors,
    looks up the owning worktree via `FindWorktreeForBranch` and emits
    `switch_to_worktree_requested(path)`. On all other errors, re-raises.
    """

    switch_to_worktree_requested = Signal(str)  # absolute path

    def __init__(self, checkout, finder, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._checkout = checkout
        self._finder = finder

    def execute(self, branch: str) -> None:
        try:
            self._checkout.execute(branch)
        except Exception as e:
            if not _looks_like_worktree_collision(e):
                raise
            wt = self._finder.execute(branch)
            if wt is None:
                raise
            self.switch_to_worktree_requested.emit(str(wt.path))
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `uv run pytest tests/presentation/services/test_smart_checkout.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
rtk git add git_gui/presentation/services/smart_checkout.py tests/presentation/services/test_smart_checkout.py
rtk git commit -m "presentation(services): add SmartCheckout for worktree-collision handling"
```

---

## Task 8: `AddWorktreeDialog`

Single MD3 dialog with branch combo, "Create new branch" checkbox (flips combo to a name field + base-ref combo), location field that live-updates with a template until manually edited, and a "Switch to new worktree after creating" checkbox.

The dialog DOES NOT execute the command itself — it emits a signal with the values, and `MainWindow` runs the command on a worker thread (mirrors how `_RemoteSignals` works for push/pull/fetch).

**Files:**
- Create: `git_gui/presentation/dialogs/add_worktree_dialog.py`
- Create: `tests/presentation/dialogs/test_add_worktree_dialog.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/presentation/dialogs/test_add_worktree_dialog.py`:
```python
"""Signal-contract tests for AddWorktreeDialog."""
from __future__ import annotations
from pathlib import Path

import pytest

from git_gui.presentation.dialogs.add_worktree_dialog import AddWorktreeDialog


def _open_dialog(qtbot, *, repo_path="/tmp/repo", branches=None,
                 in_use=None, preselect=None, default_create=False):
    dlg = AddWorktreeDialog(
        repo_path=repo_path,
        branches=branches or ["master", "feat/a", "feat/b"],
        branches_in_use={} if in_use is None else in_use,
        preselect_branch=preselect,
        default_create_new=default_create,
    )
    qtbot.addWidget(dlg)
    return dlg


def test_default_path_template_updates_with_branch_selection(qtbot):
    dlg = _open_dialog(qtbot, repo_path="/tmp/myrepo",
                      branches=["master", "feat/a"], preselect="feat/a")
    assert dlg.location() == "/tmp/myrepo-feat-a"


def test_manual_path_edit_pins_value(qtbot):
    dlg = _open_dialog(qtbot, repo_path="/tmp/myrepo", branches=["master", "x"])
    dlg.set_location("/custom/path")
    dlg.select_branch("x")
    assert dlg.location() == "/custom/path"


def test_create_new_toggle_flips_to_name_field(qtbot):
    dlg = _open_dialog(qtbot)
    dlg.set_create_new(True)
    assert dlg.is_create_new() is True
    dlg.set_new_branch_name("feat/z")
    dlg.set_base_ref("master")
    assert dlg.new_branch_name() == "feat/z"
    assert dlg.base_ref() == "master"


def test_branches_in_use_are_disabled_with_tooltip(qtbot):
    dlg = _open_dialog(
        qtbot,
        branches=["master", "feat/a", "feat/b"],
        in_use={"feat/a": "/tmp/wt-feat-a"},
    )
    assert dlg.branch_disabled("feat/a") is True
    tooltip = dlg.branch_tooltip("feat/a") or ""
    assert "/tmp/wt-feat-a" in tooltip


def test_submit_emits_add_requested_with_values(qtbot):
    dlg = _open_dialog(qtbot, branches=["master"], preselect="master")
    dlg.set_location("/tmp/x")
    received: list = []
    dlg.add_requested.connect(lambda v: received.append(v))
    with qtbot.waitSignal(dlg.add_requested, timeout=1000):
        dlg.submit()
    assert received and received[0] == {
        "branch": "master",
        "create_new": False,
        "base_ref": None,
        "location": "/tmp/x",
        "switch_after": True,
    }


def test_submit_with_create_new_emits_correct_payload(qtbot):
    dlg = _open_dialog(qtbot, branches=["master"])
    dlg.set_create_new(True)
    dlg.set_new_branch_name("feat/new")
    dlg.set_base_ref("master")
    dlg.set_location("/tmp/wt-feat-new")
    received: list = []
    dlg.add_requested.connect(lambda v: received.append(v))
    dlg.submit()
    assert received[0]["branch"] == "feat/new"
    assert received[0]["create_new"] is True
    assert received[0]["base_ref"] == "master"
    assert received[0]["location"] == "/tmp/wt-feat-new"


def test_add_button_disabled_until_valid(qtbot):
    dlg = _open_dialog(qtbot, branches=["master"])
    dlg.set_location("")
    assert dlg.add_button_enabled() is False
    dlg.set_location("/tmp/x")
    assert dlg.add_button_enabled() is True
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/presentation/dialogs/test_add_worktree_dialog.py -v`
Expected: FAIL with `ImportError` — dialog module not found.

- [ ] **Step 3: Implement the dialog**

Create `git_gui/presentation/dialogs/add_worktree_dialog.py`:
```python
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)


def _sanitize_branch(branch: str) -> str:
    """Replace path-unfriendly chars in a branch name for the default path."""
    return branch.replace("/", "-")


def _default_location(repo_path: str, branch: str) -> str:
    """Compute `{repo_parent}/{repo_name}-{sanitized_branch}`."""
    p = Path(repo_path)
    parent = p.parent
    name = p.name or "worktree"
    return str(parent / f"{name}-{_sanitize_branch(branch or 'new')}")


class AddWorktreeDialog(QDialog):
    add_requested = Signal(dict)  # {branch, create_new, base_ref, location, switch_after}
    switch_to_existing_requested = Signal(str)  # path of the owning worktree

    def __init__(
        self,
        repo_path: str,
        branches: list[str],
        branches_in_use: dict[str, str] | None = None,
        preselect_branch: str | None = None,
        default_create_new: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Worktree")
        self._repo_path = repo_path
        self._branches_in_use = dict(branches_in_use or {})
        self._location_dirty = False  # True once user manually edits the path

        # Branch combo (existing-branch mode).
        self._branch_combo = QComboBox()
        for b in branches:
            self._branch_combo.addItem(b)
            if b in self._branches_in_use:
                idx = self._branch_combo.count() - 1
                item = self._branch_combo.model().item(idx)
                item.setEnabled(False)
                item.setToolTip(f"Already checked out at {self._branches_in_use[b]}")

        # Create-new mode widgets.
        self._new_name = QLineEdit()
        self._new_name.setPlaceholderText("feature/my-branch")
        self._base_ref = QComboBox()
        for b in branches:
            self._base_ref.addItem(b)
        new_branch_widget = QWidget()
        new_form = QFormLayout(new_branch_widget)
        new_form.setContentsMargins(0, 0, 0, 0)
        new_form.addRow("New name:", self._new_name)
        new_form.addRow("Base ref:", self._base_ref)

        # Switch between existing-combo and new-name field.
        self._mode_stack = QStackedWidget()
        existing_widget = QWidget()
        existing_layout = QHBoxLayout(existing_widget)
        existing_layout.setContentsMargins(0, 0, 0, 0)
        existing_layout.addWidget(self._branch_combo)
        self._mode_stack.addWidget(existing_widget)
        self._mode_stack.addWidget(new_branch_widget)

        # "Create new branch" checkbox above the stack.
        self._create_new_cb = QCheckBox("Create new branch")
        self._create_new_cb.toggled.connect(self._on_create_new_toggled)

        # Location row.
        self._location_edit = QLineEdit()
        self._location_edit.textEdited.connect(self._on_location_edited)
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.clicked.connect(self._on_browse)
        loc_row = QHBoxLayout()
        loc_row.addWidget(self._location_edit, 1)
        loc_row.addWidget(self._browse_btn)

        # Switch-after checkbox.
        self._switch_after_cb = QCheckBox("Switch to new worktree after creating")
        self._switch_after_cb.setChecked(True)

        # Form layout.
        form = QFormLayout()
        form.addRow("Branch:", self._create_new_cb)
        form.addRow("", self._mode_stack)
        form.addRow("Location:", loc_row)
        form.addRow("", self._switch_after_cb)

        # Buttons.
        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Add")
        self._buttons.accepted.connect(self.submit)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

        # Live-update the location template.
        self._branch_combo.currentTextChanged.connect(self._on_branch_changed)
        self._new_name.textChanged.connect(self._on_new_name_changed)

        # Initial preselect + state.
        self._create_new_cb.setChecked(default_create_new)
        if preselect_branch and preselect_branch in branches and not default_create_new:
            idx = self._branch_combo.findText(preselect_branch)
            if idx >= 0:
                self._branch_combo.setCurrentIndex(idx)
        self._refresh_default_location()
        self._refresh_add_button()

    # ── Public state accessors (used by tests + callers) ────────────────

    def is_create_new(self) -> bool:
        return self._create_new_cb.isChecked()

    def set_create_new(self, value: bool) -> None:
        self._create_new_cb.setChecked(value)

    def select_branch(self, name: str) -> None:
        idx = self._branch_combo.findText(name)
        if idx >= 0:
            self._branch_combo.setCurrentIndex(idx)

    def new_branch_name(self) -> str:
        return self._new_name.text().strip()

    def set_new_branch_name(self, name: str) -> None:
        self._new_name.setText(name)

    def base_ref(self) -> str:
        return self._base_ref.currentText().strip()

    def set_base_ref(self, name: str) -> None:
        idx = self._base_ref.findText(name)
        if idx >= 0:
            self._base_ref.setCurrentIndex(idx)

    def location(self) -> str:
        return self._location_edit.text().strip()

    def set_location(self, value: str) -> None:
        # Programmatic set leaves the dirty bit alone (used in tests).
        self._location_edit.setText(value)
        self._location_dirty = True if value else self._location_dirty
        self._refresh_add_button()

    def add_button_enabled(self) -> bool:
        return self._buttons.button(QDialogButtonBox.Ok).isEnabled()

    def branch_disabled(self, name: str) -> bool:
        idx = self._branch_combo.findText(name)
        if idx < 0:
            return False
        return not self._branch_combo.model().item(idx).isEnabled()

    def branch_tooltip(self, name: str) -> str | None:
        idx = self._branch_combo.findText(name)
        if idx < 0:
            return None
        return self._branch_combo.model().item(idx).toolTip() or None

    # ── Handlers ─────────────────────────────────────────────────────────

    def _on_create_new_toggled(self, on: bool) -> None:
        self._mode_stack.setCurrentIndex(1 if on else 0)
        self._refresh_default_location()
        self._refresh_add_button()

    def _on_branch_changed(self, _text: str) -> None:
        self._refresh_default_location()
        self._refresh_add_button()

    def _on_new_name_changed(self, _text: str) -> None:
        self._refresh_default_location()
        self._refresh_add_button()

    def _on_location_edited(self, text: str) -> None:
        self._location_dirty = True
        self._refresh_add_button()

    def _on_browse(self) -> None:
        d = QFileDialog(self, "Choose worktree location")
        d.setFileMode(QFileDialog.Directory)
        d.setOption(QFileDialog.ShowDirsOnly, True)
        if d.exec() == QFileDialog.Accepted:
            files = d.selectedFiles()
            if files:
                self._location_edit.setText(files[0])
                self._location_dirty = True
                self._refresh_add_button()

    def _current_branch(self) -> str:
        if self.is_create_new():
            return self.new_branch_name()
        return self._branch_combo.currentText().strip()

    def _refresh_default_location(self) -> None:
        if self._location_dirty:
            return
        branch = self._current_branch()
        self._location_edit.setText(_default_location(self._repo_path, branch))

    def _refresh_add_button(self) -> None:
        branch = self._current_branch()
        loc = self.location()
        valid = bool(branch) and bool(loc)
        if not self.is_create_new() and self.branch_disabled(branch):
            valid = False
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(valid)

    def submit(self) -> None:
        payload = {
            "branch": self._current_branch(),
            "create_new": self.is_create_new(),
            "base_ref": self.base_ref() if self.is_create_new() else None,
            "location": self.location(),
            "switch_after": self._switch_after_cb.isChecked(),
        }
        self.add_requested.emit(payload)
        self.accept()
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/presentation/dialogs/test_add_worktree_dialog.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
rtk git add git_gui/presentation/dialogs/add_worktree_dialog.py tests/presentation/dialogs/test_add_worktree_dialog.py
rtk git commit -m "presentation(dialog): add AddWorktreeDialog with templated default path"
```

---

## Task 9: `WorktreesDialog` (Manage)

Table view of all worktrees with Open / Lock / Unlock / Remove actions and an "Add Worktree…" button. Mirrors `submodule_dialog.py`'s structure.

**Files:**
- Create: `git_gui/presentation/dialogs/worktrees_dialog.py`
- Create: `tests/presentation/dialogs/test_worktrees_dialog.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/presentation/dialogs/test_worktrees_dialog.py`:
```python
"""Signal-contract tests for WorktreesDialog."""
from __future__ import annotations
from pathlib import Path

from git_gui.domain.entities import Worktree
from git_gui.presentation.dialogs.worktrees_dialog import WorktreesDialog


def _wt(branch="feat", path="/tmp/wt", locked=False, reason=None, main=False):
    return Worktree(
        path=Path(path), branch=branch, head_sha="abc",
        is_locked=locked, lock_reason=reason, is_bare=False, is_main=main,
    )


def _open(qtbot, worktrees):
    dlg = WorktreesDialog(worktrees=worktrees)
    qtbot.addWidget(dlg)
    return dlg


def test_rows_render_branch_and_path(qtbot):
    dlg = _open(qtbot, [_wt("main", "/tmp/main", main=True),
                        _wt("feat", "/tmp/wt-feat")])
    assert dlg.row_count() == 2
    assert dlg.row_branch(0) == "main"
    assert dlg.row_path(1) == "/tmp/wt-feat"


def test_locked_column_shows_reason(qtbot):
    dlg = _open(qtbot, [_wt("feat", locked=True, reason="busy")])
    assert "busy" in dlg.row_locked_text(0).lower() or dlg.row_locked_text(0) == "Locked"


def test_open_button_emits_open_requested(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat")])
    received: list[str] = []
    dlg.open_requested.connect(received.append)
    dlg.select_row(0)
    dlg.click_open()
    assert received == ["/tmp/wt-feat"]


def test_remove_button_emits_remove_requested(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat")])
    received: list[str] = []
    dlg.remove_requested.connect(received.append)
    dlg.select_row(0)
    dlg.click_remove()
    assert received == ["/tmp/wt-feat"]


def test_lock_button_emits_lock_requested_for_unlocked_row(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat", locked=False)])
    received: list = []
    dlg.lock_requested.connect(lambda p, r: received.append((p, r)))
    dlg.select_row(0)
    # Simulate user entering a reason and confirming.
    dlg.click_lock(reason_for_test="overnight")
    assert received == [("/tmp/wt-feat", "overnight")]


def test_unlock_button_emits_unlock_requested_for_locked_row(qtbot):
    dlg = _open(qtbot, [_wt("feat", "/tmp/wt-feat", locked=True)])
    received: list[str] = []
    dlg.unlock_requested.connect(received.append)
    dlg.select_row(0)
    dlg.click_unlock()
    assert received == ["/tmp/wt-feat"]


def test_add_button_emits_add_requested(qtbot):
    dlg = _open(qtbot, [])
    received: list = []
    dlg.add_requested.connect(lambda: received.append(True))
    dlg.click_add()
    assert received == [True]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/presentation/dialogs/test_worktrees_dialog.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the dialog**

Create `git_gui/presentation/dialogs/worktrees_dialog.py`:
```python
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from git_gui.domain.entities import Worktree


class WorktreesDialog(QDialog):
    open_requested = Signal(str)          # absolute path
    remove_requested = Signal(str)
    lock_requested = Signal(str, str)     # path, reason (may be empty)
    unlock_requested = Signal(str)
    add_requested = Signal()

    def __init__(self, worktrees: list[Worktree] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Worktrees")
        self.resize(720, 420)
        self._worktrees: list[Worktree] = list(worktrees or [])

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Branch", "Path", "Locked", "Status"])
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)

        self._open_btn = QPushButton("Open")
        self._lock_btn = QPushButton("Lock…")
        self._unlock_btn = QPushButton("Unlock")
        self._remove_btn = QPushButton("Remove…")
        self._add_btn = QPushButton("Add Worktree…")
        self._close_btn = QPushButton("Close")

        self._open_btn.clicked.connect(self._on_open)
        self._lock_btn.clicked.connect(lambda: self._on_lock())
        self._unlock_btn.clicked.connect(self._on_unlock)
        self._remove_btn.clicked.connect(self._on_remove)
        self._add_btn.clicked.connect(lambda: self.add_requested.emit())
        self._close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._open_btn)
        btn_row.addWidget(self._lock_btn)
        btn_row.addWidget(self._unlock_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addLayout(btn_row)

        self._populate()

    # ── Public test/inspection API ───────────────────────────────────────

    def row_count(self) -> int:
        return self._table.rowCount()

    def row_branch(self, row: int) -> str:
        return self._table.item(row, 0).text()

    def row_path(self, row: int) -> str:
        return self._table.item(row, 1).text()

    def row_locked_text(self, row: int) -> str:
        return self._table.item(row, 2).text()

    def select_row(self, row: int) -> None:
        self._table.selectRow(row)

    def click_open(self) -> None:
        self._on_open()

    def click_remove(self) -> None:
        self._on_remove()

    def click_lock(self, reason_for_test: str | None = None) -> None:
        # Test seam: bypass QInputDialog by passing reason directly.
        self._on_lock(reason_override=reason_for_test)

    def click_unlock(self) -> None:
        self._on_unlock()

    def click_add(self) -> None:
        self.add_requested.emit()

    # ── Internals ────────────────────────────────────────────────────────

    def _populate(self) -> None:
        self._table.setRowCount(0)
        for wt in self._worktrees:
            row = self._table.rowCount()
            self._table.insertRow(row)
            branch = wt.branch or "(detached)"
            self._table.setItem(row, 0, QTableWidgetItem(branch))
            self._table.setItem(row, 1, QTableWidgetItem(str(wt.path)))
            locked_text = ""
            if wt.is_locked:
                locked_text = wt.lock_reason or "Locked"
            self._table.setItem(row, 2, QTableWidgetItem(locked_text))
            self._table.setItem(row, 3, QTableWidgetItem("main" if wt.is_main else ""))

    def _selected_path(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 1).text()

    def _selected_worktree(self) -> Worktree | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._worktrees[rows[0].row()]

    def _on_open(self) -> None:
        path = self._selected_path()
        if path:
            self.open_requested.emit(path)

    def _on_remove(self) -> None:
        path = self._selected_path()
        if path:
            self.remove_requested.emit(path)

    def _on_lock(self, reason_override: str | None = None) -> None:
        path = self._selected_path()
        if not path:
            return
        if reason_override is None:
            text, ok = QInputDialog.getText(self, "Lock Worktree", "Reason (optional):")
            if not ok:
                return
            reason = text.strip()
        else:
            reason = reason_override
        self.lock_requested.emit(path, reason)

    def _on_unlock(self) -> None:
        path = self._selected_path()
        if path:
            self.unlock_requested.emit(path)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/presentation/dialogs/test_worktrees_dialog.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
rtk git add git_gui/presentation/dialogs/worktrees_dialog.py tests/presentation/dialogs/test_worktrees_dialog.py
rtk git commit -m "presentation(dialog): add WorktreesDialog (manage list)"
```

---

## Task 10: `RepoListWidget` — render worktrees as QTreeView children

The widget's `_tree` is already a `QTreeView` with a `QStandardItemModel`. The OPEN section currently appends repo items as direct children of an "OPEN" header. We extend `reload()` to accept an optional list of worktrees for the active repo, and to attach those worktrees as child items of the active-repo row. Other repos in OPEN remain leaf items.

We also need a small protocol for the click on a worktree child row to fire `repo_switch_requested` with the worktree's path.

**Files:**
- Modify: `git_gui/presentation/widgets/repo_list.py`
- Create: `tests/presentation/widgets/test_repo_list_worktrees.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/presentation/widgets/test_repo_list_worktrees.py`:
```python
"""Worktree children rendering in RepoListWidget."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt

from git_gui.domain.entities import Worktree
from git_gui.presentation.widgets.repo_list import RepoListWidget


class _FakeStore:
    def __init__(self, open_=None, recent=None, active=None):
        self._open = list(open_ or [])
        self._recent = list(recent or [])
        self._active = active
    def load(self): pass
    def save(self): pass
    def get_open_repos(self): return list(self._open)
    def get_recent_repos(self): return list(self._recent)
    def get_active(self): return self._active
    def add_open(self, p, after=None):
        if p in self._open: return
        if after and after in self._open:
            self._open.insert(self._open.index(after) + 1, p)
        else:
            self._open.append(p)
    def close_repo(self, p):
        if p in self._open: self._open.remove(p)
    def remove_recent(self, p):
        if p in self._recent: self._recent.remove(p)
    def set_active(self, p): self._active = p
    def set_open_order(self, paths): self._open = list(paths)


def _wt(path, branch="feat"):
    return Worktree(
        path=Path(path), branch=branch, head_sha="abc",
        is_locked=False, lock_reason=None, is_bare=False, is_main=False,
    )


def test_active_repo_worktrees_render_as_children(qtbot, tmp_path):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees([
        _wt("/tmp/myrepo", branch="master"),  # main
        _wt("/tmp/myrepo-feat", branch="feat"),
    ])
    w.reload()
    # The model should have a child row under the active repo row for the
    # linked worktree (main worktree is implicit — the active repo row itself).
    model = w._model
    open_header = None
    for row in range(model.rowCount()):
        item = model.item(row)
        if item.data(Qt.UserRole + 1) == "header" and item.text() == "OPEN":
            open_header = item
            break
    assert open_header is not None
    repo_item = open_header.child(0)
    assert repo_item.rowCount() == 1
    wt_child = repo_item.child(0)
    assert wt_child.data(Qt.UserRole) == "/tmp/myrepo-feat"
    assert wt_child.data(Qt.UserRole + 1) == "worktree"


def test_inactive_repos_do_not_show_worktree_children(qtbot):
    store = _FakeStore(
        open_=["/tmp/myrepo", "/tmp/other"], active="/tmp/myrepo",
    )
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees([_wt("/tmp/myrepo-feat")])
    w.reload()
    model = w._model
    open_header = next(
        model.item(r) for r in range(model.rowCount())
        if model.item(r).data(Qt.UserRole + 1) == "header"
        and model.item(r).text() == "OPEN"
    )
    other_item = open_header.child(1)
    assert other_item.rowCount() == 0


def test_clicking_worktree_child_emits_repo_switch_requested(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees([_wt("/tmp/myrepo-feat")])
    w.reload()
    received: list[str] = []
    w.repo_switch_requested.connect(received.append)
    # Find the worktree child index and simulate a click via the handler.
    model = w._model
    open_header = next(
        model.item(r) for r in range(model.rowCount())
        if model.item(r).text() == "OPEN"
    )
    repo_item = open_header.child(0)
    wt_child = repo_item.child(0)
    w._on_item_clicked(model.indexFromItem(wt_child))
    assert received == ["/tmp/myrepo-feat"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/presentation/widgets/test_repo_list_worktrees.py -v`
Expected: FAIL with `AttributeError` — `set_active_worktrees` not defined.

- [ ] **Step 3: Extend `RepoListWidget`**

Edit `git_gui/presentation/widgets/repo_list.py`. Add `Worktree` import near the top:
```python
from git_gui.domain.entities import Worktree
```

In `RepoListWidget.__init__`, after `self._store = repo_store`, initialize the worktree state:
```python
        self._active_worktrees: list[Worktree] = []
```

Right after the `__init__` body, before `reload`, add:
```python
    def set_active_worktrees(self, worktrees: list[Worktree]) -> None:
        """Set the worktrees to render under the active repo row."""
        self._active_worktrees = list(worktrees)
```

Then in `reload`, after creating each open repo item, attach worktree children when the repo is active. Replace the `for path in open_repos:` block with:
```python
            for path in open_repos:
                item = self._make_repo_item(path, "open", is_active=(path == active))
                if path == active and self._active_worktrees:
                    for wt in self._active_worktrees:
                        if wt.is_main:
                            continue  # main worktree IS the active repo row
                        item.appendRow(self._make_worktree_item(wt))
                open_header.appendRow(item)
```

Add `_make_worktree_item` as a new method on `RepoListWidget`:
```python
    def _make_worktree_item(self, wt: Worktree) -> QStandardItem:
        label = wt.branch or "(detached)"
        item = QStandardItem(label)
        item.setEditable(False)
        item.setToolTip(str(wt.path))
        item.setData(str(wt.path), Qt.UserRole)
        item.setData("worktree", Qt.UserRole + 1)
        return item
```

Extend `_on_item_clicked` to handle the new kind:
```python
    def _on_item_clicked(self, index) -> None:
        kind = index.data(Qt.UserRole + 1)
        path = index.data(Qt.UserRole)
        if kind == "open" and path:
            self.repo_switch_requested.emit(path)
        elif kind == "recent" and path:
            self.repo_open_requested.emit(path)
        elif kind == "worktree" and path:
            self.repo_switch_requested.emit(path)
```

Enable expandable rows. In `__init__` after `self._tree.setRootIsDecorated(False)`, change that line to:
```python
        self._tree.setRootIsDecorated(True)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/presentation/widgets/test_repo_list_worktrees.py -v`
Expected: 3 passed.

Also run the existing repo_list tests if any:
Run: `uv run pytest tests/presentation/widgets/ -v`
Expected: previously-passing tests still pass.

- [ ] **Step 5: Commit**

```bash
rtk git add git_gui/presentation/widgets/repo_list.py tests/presentation/widgets/test_repo_list_worktrees.py
rtk git commit -m "presentation(repo_list): nest worktrees under the active repo row"
```

---

## Task 11: Repo-list context menus for worktrees

Add context-menu entries:
- On the active-repo row: "Add Worktree…", "Manage Worktrees…"
- On a worktree child row: "Open", "Lock…", "Unlock", "Remove…"

Emits a new signal `worktree_action_requested(action, path)` to keep the widget decoupled from MainWindow.

**Files:**
- Modify: `git_gui/presentation/widgets/repo_list.py`
- Modify: `tests/presentation/widgets/test_repo_list_worktrees.py` (add a few tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/presentation/widgets/test_repo_list_worktrees.py`:
```python
from PySide6.QtCore import QPoint


def test_context_menu_on_active_repo_has_add_and_manage(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees([])
    w.reload()
    actions = w._build_context_actions_for_active_repo("/tmp/myrepo")
    labels = [a["label"] for a in actions]
    assert "Add Worktree…" in labels
    assert "Manage Worktrees…" in labels


def test_context_menu_on_worktree_row_has_open_lock_remove(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.set_active_worktrees([_wt("/tmp/myrepo-feat", branch="feat")])
    w.reload()
    actions = w._build_context_actions_for_worktree("/tmp/myrepo-feat", locked=False)
    labels = [a["label"] for a in actions]
    assert "Open" in labels
    assert "Lock…" in labels
    assert "Remove…" in labels
    assert "Unlock" not in labels


def test_context_menu_on_locked_worktree_shows_unlock_not_lock(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    w.reload()
    actions = w._build_context_actions_for_worktree("/tmp/locked", locked=True)
    labels = [a["label"] for a in actions]
    assert "Unlock" in labels
    assert "Lock…" not in labels


def test_worktree_action_signal_emits(qtbot):
    store = _FakeStore(open_=["/tmp/myrepo"], active="/tmp/myrepo")
    w = RepoListWidget(store)
    qtbot.addWidget(w)
    received: list = []
    w.worktree_action_requested.connect(lambda a, p: received.append((a, p)))
    w._emit_worktree_action("add", "/tmp/myrepo")
    w._emit_worktree_action("remove", "/tmp/myrepo-feat")
    assert received == [("add", "/tmp/myrepo"), ("remove", "/tmp/myrepo-feat")]
```

- [ ] **Step 2: Run and verify the new tests fail**

Run: `uv run pytest tests/presentation/widgets/test_repo_list_worktrees.py -v`
Expected: 4 new tests fail with `AttributeError`.

- [ ] **Step 3: Implement signal + helpers**

In `git_gui/presentation/widgets/repo_list.py`, add the new signal in the class-level declarations near `repo_switch_requested`:
```python
    worktree_action_requested = Signal(str, str)  # (action, path) — action ∈ {"add", "manage", "open", "lock", "unlock", "remove"}
```

Add the action builders and emitter near the bottom of the class:
```python
    def _build_context_actions_for_active_repo(self, path: str) -> list[dict]:
        return [
            {"label": "Add Worktree…", "action": "add", "path": path},
            {"label": "Manage Worktrees…", "action": "manage", "path": path},
        ]

    def _build_context_actions_for_worktree(self, path: str, *, locked: bool) -> list[dict]:
        actions = [{"label": "Open", "action": "open", "path": path}]
        if locked:
            actions.append({"label": "Unlock", "action": "unlock", "path": path})
        else:
            actions.append({"label": "Lock…", "action": "lock", "path": path})
        actions.append({"label": "Remove…", "action": "remove", "path": path})
        return actions

    def _emit_worktree_action(self, action: str, path: str) -> None:
        self.worktree_action_requested.emit(action, path)
```

Extend `_show_context_menu` to drive these:
```python
    def _show_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        kind = index.data(Qt.UserRole + 1)
        path = index.data(Qt.UserRole)
        active = self._store.get_active()

        menu = QMenu(self)
        if kind == "open" and path:
            menu.addAction("Close").triggered.connect(
                lambda: self.repo_close_requested.emit(path))
            if path == active:
                menu.addSeparator()
                for entry in self._build_context_actions_for_active_repo(path):
                    a = menu.addAction(entry["label"])
                    a.triggered.connect(
                        lambda _checked=False, e=entry: self._emit_worktree_action(e["action"], e["path"])
                    )
        elif kind == "worktree" and path:
            locked = self._is_worktree_locked(path)
            for entry in self._build_context_actions_for_worktree(path, locked=locked):
                a = menu.addAction(entry["label"])
                a.triggered.connect(
                    lambda _checked=False, e=entry: self._emit_worktree_action(e["action"], e["path"])
                )
        elif kind == "recent" and path:
            menu.addAction("Remove from recent").triggered.connect(
                lambda: self.repo_remove_recent_requested.emit(path))
        elif kind == "header":
            title = index.data(Qt.DisplayRole)
            if title == "OPEN":
                menu.addAction("Open Repository...").triggered.connect(self._on_add_clicked)
                menu.addAction("Clone Repository...").triggered.connect(
                    lambda: self.clone_requested.emit())
            else:
                return
        else:
            return
        menu.exec(self._tree.viewport().mapToGlobal(pos))
```

Add `_is_worktree_locked`:
```python
    def _is_worktree_locked(self, path: str) -> bool:
        for wt in self._active_worktrees:
            if str(wt.path) == path:
                return wt.is_locked
        return False
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/presentation/widgets/test_repo_list_worktrees.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
rtk git add git_gui/presentation/widgets/repo_list.py tests/presentation/widgets/test_repo_list_worktrees.py
rtk git commit -m "presentation(repo_list): add worktree context menus"
```

---

## Task 12: `RepoChangeDetector` — watch `.git/worktrees/`

Add the worktrees metadata directory to the existing watch list so external `git worktree add/remove/prune` mutations trigger a UI reload.

**Files:**
- Modify: `git_gui/presentation/services/repo_change_detector.py`
- Create: `tests/presentation/services/test_repo_change_detector_worktrees.py`

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/services/test_repo_change_detector_worktrees.py`:
```python
"""RepoChangeDetector should watch .git/worktrees/ for external worktree
add/remove/prune operations."""
from __future__ import annotations
import os
import subprocess

import pygit2
import pytest

from git_gui.presentation.services.repo_change_detector import RepoChangeDetector


@pytest.fixture
def repo(tmp_path):
    p = tmp_path / "r"
    repo = pygit2.init_repository(str(p))
    repo.config["user.name"] = "T"
    repo.config["user.email"] = "t@e.com"
    sig = pygit2.Signature("T", "t@e.com")
    (p / "a.txt").write_text("x")
    repo.index.add("a.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("refs/heads/master", sig, sig, "init", tree, [])
    # Ensure .git/worktrees/ exists so the watcher has something to attach to.
    (p / ".git" / "worktrees").mkdir(exist_ok=True)
    return p


def test_worktrees_dir_is_in_watch_set(qtbot, repo):
    d = RepoChangeDetector(str(repo), on_reload=lambda: None)
    try:
        watched = set(d._watcher.directories())
        assert str(repo / ".git" / "worktrees") in watched
    finally:
        d.stop()


def test_external_worktree_add_triggers_reload(qtbot, repo, tmp_path):
    calls: list[None] = []
    d = RepoChangeDetector(str(repo), on_reload=lambda: calls.append(None))
    try:
        # Add a branch + worktree externally.
        gitrepo = pygit2.Repository(str(repo))
        gitrepo.references.create("refs/heads/feat", gitrepo.head.target)
        wt_path = tmp_path / "wt-feat"
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", str(wt_path), "feat"],
            check=True, capture_output=True,
        )
        # Allow filesystem events + debounce to fire.
        qtbot.wait(500)
        assert calls, "expected on_reload to fire after external worktree add"
    finally:
        d.stop()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/presentation/services/test_repo_change_detector_worktrees.py -v`
Expected: FAIL — `.git/worktrees/` not yet in the watch set.

- [ ] **Step 3: Extend the watch list**

Edit `git_gui/presentation/services/repo_change_detector.py`. In `_add_git_watch_paths`, append `git_dir / "worktrees"` to the `dirs` list:
```python
        dirs = [
            git_dir,
            git_dir / "refs" / "heads",
            git_dir / "refs" / "remotes",
            git_dir / "refs" / "tags",
            git_dir / "logs",
            git_dir / "worktrees",
        ]
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/presentation/services/test_repo_change_detector_worktrees.py -v`
Expected: 2 passed.

Also run the full RepoChangeDetector suite to ensure nothing regressed:
Run: `uv run pytest tests/presentation/services/ -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
rtk git add git_gui/presentation/services/repo_change_detector.py tests/presentation/services/test_repo_change_detector_worktrees.py
rtk git commit -m "presentation(detector): watch .git/worktrees for external changes"
```

---

## Task 13: Sidebar `+` badge + "Checkout in New Worktree…" context menu

Tower-style `+` after a branch name in the in-repo `sidebar.py` branch tree, plus a new context-menu item that opens the Add Worktree dialog pre-populated with that branch.

The sidebar already has a branch tree; we extend it to accept a `set_worktree_branches(set[str])` setter and render the badge for matched rows.

**Files:**
- Modify: `git_gui/presentation/widgets/sidebar.py`
- Create: `tests/presentation/widgets/test_sidebar_worktree_badge.py`

- [ ] **Step 1: Read the existing sidebar to find the branch-row rendering path**

Run: `uv run python -c "import pathlib; print(pathlib.Path('git_gui/presentation/widgets/sidebar.py').read_text()[:4000])"`

Find:
- The class name (likely `Sidebar`) and the method that builds branch items.
- The method that builds the right-click context menu for a branch row.

Note the exact method names for use in the next steps; the snippets below use placeholder names that may need adjusting (verify by reading).

- [ ] **Step 2: Write the failing tests**

Create `tests/presentation/widgets/test_sidebar_worktree_badge.py`:
```python
"""Sidebar branch rows show a + badge when the branch owns a worktree,
and the branch context menu offers 'Checkout in New Worktree…'."""
from __future__ import annotations

import pytest

from git_gui.presentation.widgets.sidebar import Sidebar


def test_set_worktree_branches_updates_state(qtbot):
    sb = Sidebar()
    qtbot.addWidget(sb)
    sb.set_worktree_branches({"feat/a"})
    assert sb.has_worktree_badge("feat/a") is True
    assert sb.has_worktree_badge("master") is False


def test_branch_context_menu_contains_checkout_in_new_worktree(qtbot):
    sb = Sidebar()
    qtbot.addWidget(sb)
    actions = sb.build_branch_context_actions("feat/a")
    labels = [a["label"] for a in actions]
    assert "Checkout in New Worktree…" in labels


def test_checkout_in_new_worktree_action_emits_signal(qtbot):
    sb = Sidebar()
    qtbot.addWidget(sb)
    received: list[str] = []
    sb.checkout_in_new_worktree_requested.connect(received.append)
    sb.trigger_branch_action("checkout_in_new_worktree", "feat/a")
    assert received == ["feat/a"]
```

- [ ] **Step 3: Run and verify the tests fail**

Run: `uv run pytest tests/presentation/widgets/test_sidebar_worktree_badge.py -v`
Expected: FAIL with `AttributeError` (the helpers don't exist yet).

- [ ] **Step 4: Implement the helpers in `sidebar.py`**

Edit `git_gui/presentation/widgets/sidebar.py`. Near the other `Signal(...)` declarations on the `Sidebar` class, add:
```python
    checkout_in_new_worktree_requested = Signal(str)  # branch name
```

In `Sidebar.__init__`, initialize the state:
```python
        self._worktree_branches: set[str] = set()
```

Add the public setters/inspectors:
```python
    def set_worktree_branches(self, branches: set[str]) -> None:
        """Set the names of branches currently checked out in a worktree.
        Rows for these branches will render with a '+' badge."""
        self._worktree_branches = set(branches)
        self._refresh_branch_badges()

    def has_worktree_badge(self, branch: str) -> bool:
        return branch in self._worktree_branches

    def build_branch_context_actions(self, branch: str) -> list[dict]:
        # Existing actions stay where they were; we add the new one alongside.
        actions = self._existing_branch_context_actions(branch)
        actions.append({
            "label": "Checkout in New Worktree…",
            "action": "checkout_in_new_worktree",
            "branch": branch,
        })
        return actions

    def trigger_branch_action(self, action: str, branch: str) -> None:
        if action == "checkout_in_new_worktree":
            self.checkout_in_new_worktree_requested.emit(branch)
```

Add a `_refresh_branch_badges` method that walks the branch tree model and updates each branch row's display text. Inside the branch-row delegate (or wherever the row label is built), append `"  +"` to the displayed text when the branch is in `self._worktree_branches`, with a tooltip noting the worktree. If the existing code uses a delegate (`ref_badge_delegate.py` exists), prefer extending the delegate to consume the `_worktree_branches` set. As a fallback, mutate the QStandardItem text directly when `set_worktree_branches` runs.

Concrete implementation depends on how branch rows are currently rendered — read `sidebar.py` and pick the smallest, least-invasive edit. The test only requires `has_worktree_badge` and the context action; full visual styling is verified during manual QA in Task 18.

If the existing class does not have an `_existing_branch_context_actions` extraction, perform a small refactor: pull the existing branch-row context-menu items into a private helper returning the same `list[dict]` shape, then append the new entry.

Wire the new context action into the `customContextMenuRequested` handler so right-clicking a branch row offers it (using the no-exec menu pattern is fine for tests).

- [ ] **Step 5: Run the tests and verify they pass**

Run: `uv run pytest tests/presentation/widgets/test_sidebar_worktree_badge.py -v`
Expected: 3 passed.

Run the existing sidebar tests to ensure no regression:
Run: `uv run pytest tests/presentation/widgets/ -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
rtk git add git_gui/presentation/widgets/sidebar.py tests/presentation/widgets/test_sidebar_worktree_badge.py
rtk git commit -m "presentation(sidebar): + badge and 'Checkout in New Worktree' context action"
```

---

## Task 14: Graph branch-ref context menu — "Checkout in New Worktree…"

The graph already has a branch-ref context menu. Add the same item; it emits a graph-level signal `checkout_in_new_worktree_requested(str)` that MainWindow connects to the same flow as the sidebar action.

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py`

- [ ] **Step 1: Locate the branch-ref context menu builder**

Read `git_gui/presentation/widgets/graph.py` and find the method that builds the context menu when right-clicking a branch ref in the graph (search for "Checkout" or "branch" + "menu" handlers).

- [ ] **Step 2: Add the signal and menu item**

In the class declaration of the graph widget, add near other branch-related signals:
```python
    checkout_in_new_worktree_requested = Signal(str)  # branch name
```

In the branch-ref context-menu builder, after the existing "Checkout" / "Create branch from…" entries, append:
```python
        act_wt = menu.addAction("Checkout in New Worktree…")
        act_wt.triggered.connect(lambda _checked=False, b=branch_name: self.checkout_in_new_worktree_requested.emit(b))
```

(`branch_name` is whatever the existing builder uses for the branch identifier — match the surrounding code.)

- [ ] **Step 3: Add a test asserting the menu builder includes the new action**

Locate the existing graph tests (`tests/presentation/widgets/test_graph*.py` if present). If none cover branch-ref context menus, add a small one:

Create or extend `tests/presentation/widgets/test_graph_branch_menu.py`:
```python
from PySide6.QtWidgets import QMenu
from git_gui.presentation.widgets.graph import GraphView  # adjust to actual class name


def test_branch_context_menu_has_checkout_in_new_worktree(qtbot, monkeypatch):
    menu_items: list[str] = []
    real_add = QMenu.addAction
    def spy(self, text, *a, **kw):
        menu_items.append(text)
        return real_add(self, text, *a, **kw)
    monkeypatch.setattr(QMenu, "addAction", spy)
    gv = GraphView()
    qtbot.addWidget(gv)
    # Trigger the builder via whatever public API exists; for example:
    gv._open_branch_context_menu("feat/x", pos=None)  # adjust to actual API
    assert "Checkout in New Worktree…" in menu_items
```

Adjust `GraphView` / `_open_branch_context_menu` to match the actual API.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/presentation/widgets/test_graph_branch_menu.py -v`
Expected: passes.

- [ ] **Step 5: Commit**

```bash
rtk git add git_gui/presentation/widgets/graph.py tests/presentation/widgets/test_graph_branch_menu.py
rtk git commit -m "presentation(graph): add 'Checkout in New Worktree…' to branch context menu"
```

---

## Task 15: `BranchesDialog` — + badge column and "Checkout in New Worktree…" button

Add a 4th column "Worktree" to the existing 3-column table that shows the worktree's path when the branch owns one. Add a "Checkout in New Worktree…" button next to "Checkout".

**Files:**
- Modify: `git_gui/presentation/dialogs/branches_dialog.py`
- Modify: `tests/presentation/dialogs/test_branches_dialog.py` if it exists, else create new tests

- [ ] **Step 1: Add the failing tests**

Create `tests/presentation/dialogs/test_branches_dialog_worktree.py`:
```python
"""Worktree integration in BranchesDialog: + badge column and new
'Checkout in New Worktree' button."""
from __future__ import annotations

from git_gui.domain.entities import LocalBranchInfo
from git_gui.presentation.dialogs.branches_dialog import BranchesDialog


class _Q:
    """Minimal QueryBus stand-in."""
    def __init__(self, infos, worktree_map=None):
        self._infos = infos
        self._wt_map = worktree_map or {}
        class _LBU:
            def __init__(self, infos): self._infos = infos
            def execute(self): return list(self._infos)
        class _GB:
            def execute(self): return []
        self.list_local_branches_with_upstream = _LBU(infos)
        self.get_branches = _GB()


class _C: ...


def _info(name, upstream=None):
    return LocalBranchInfo(
        name=name, upstream=upstream,
        last_commit_sha="abc1234", last_commit_message="msg",
    )


def test_branches_dialog_renders_worktree_column(qtbot):
    q = _Q([_info("master"), _info("feat/a")])
    dlg = BranchesDialog(q, _C())
    qtbot.addWidget(dlg)
    dlg.set_worktree_paths({"feat/a": "/tmp/wt-feat-a"})
    # Column headers should include "Worktree"
    headers = [
        dlg._table.horizontalHeaderItem(i).text()
        for i in range(dlg._table.columnCount())
    ]
    assert "Worktree" in headers
    # The row for feat/a should show the worktree path.
    for row in range(dlg._table.rowCount()):
        if dlg._table.item(row, 0).text() == "feat/a":
            col = headers.index("Worktree")
            assert "/tmp/wt-feat-a" in dlg._table.item(row, col).text()
            break
    else:
        raise AssertionError("feat/a row not found")


def test_checkout_in_new_worktree_button_emits_signal(qtbot):
    q = _Q([_info("master")])
    dlg = BranchesDialog(q, _C())
    qtbot.addWidget(dlg)
    received: list[str] = []
    dlg.checkout_in_new_worktree_requested.connect(received.append)
    dlg._table.selectRow(0)
    dlg.click_checkout_in_new_worktree()
    assert received == ["master"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/presentation/dialogs/test_branches_dialog_worktree.py -v`
Expected: FAIL — missing setter and signal.

- [ ] **Step 3: Extend the dialog**

Edit `git_gui/presentation/dialogs/branches_dialog.py`:

Add the signal near the top of `BranchesDialog`:
```python
    checkout_in_new_worktree_requested = Signal(str)  # branch name
```

(Add `from PySide6.QtCore import Signal` at top of file if not already imported.)

Change the table to 4 columns and update the header:
```python
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Name", "Upstream", "Last commit", "Worktree"])
```

Initialize the worktree map and a setter:
```python
        self._worktree_paths: dict[str, str] = {}
```
```python
    def set_worktree_paths(self, mapping: dict[str, str]) -> None:
        """Map of branch_name -> absolute worktree path. Rows for matching
        branches will display a '+' badge in the Name cell and the path
        in the Worktree column."""
        self._worktree_paths = dict(mapping)
        self._refresh()
```

In `_refresh`, after setting the existing three columns, set the fourth:
```python
            wt_path = self._worktree_paths.get(info.name, "")
            self._table.setItem(row, 3, QTableWidgetItem(wt_path))
            if wt_path:
                # Visual badge: append " +" to the name cell.
                name_item = self._table.item(row, 0)
                name_item.setText(f"{info.name}  +")
                name_item.setToolTip(f"Checked out at {wt_path}")
```

Add the new button next to "Checkout":
```python
        self._checkout_wt_btn = QPushButton("Checkout in New Worktree…")
        self._checkout_wt_btn.clicked.connect(self._on_checkout_in_new_worktree)
        # Insert into the button row (after self._checkout_btn).
        btn_row.insertWidget(1, self._checkout_wt_btn)
```

(You'll need to retain a reference to `btn_row` to call `insertWidget`. If the existing code constructs the layout inline, refactor to store `btn_row` as a local before adding it to `layout`.)

Add the handler + a test seam:
```python
    def _on_checkout_in_new_worktree(self) -> None:
        name = self._selected_name()
        if name:
            self.checkout_in_new_worktree_requested.emit(name)

    def click_checkout_in_new_worktree(self) -> None:
        self._on_checkout_in_new_worktree()
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/presentation/dialogs/test_branches_dialog_worktree.py -v`
Expected: 2 passed.

Run existing branches-dialog tests if present:
Run: `uv run pytest tests/presentation/dialogs/ -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
rtk git add git_gui/presentation/dialogs/branches_dialog.py tests/presentation/dialogs/test_branches_dialog_worktree.py
rtk git commit -m "presentation(branches): + badge column and 'Checkout in New Worktree' button"
```

---

## Task 16: Git menu — "Worktrees…" item

Add a `Worktrees…` action to the Git menu that opens the `WorktreesDialog`.

**Files:**
- Modify: `git_gui/presentation/menus/git_menu.py`

- [ ] **Step 1: Extend the menu installer**

Edit `git_gui/presentation/menus/git_menu.py`. Add the import:
```python
from git_gui.presentation.dialogs.worktrees_dialog import WorktreesDialog
```

Extend `install_git_menu` signature with two new callbacks for the worktree wiring (so MainWindow controls behavior, not the menu):
```python
def install_git_menu(
    window: QMainWindow,
    queries,
    commands,
    repo_workdir: str | None,
    on_open_submodule: Callable[[str], None],
    on_open_worktrees_dialog: Callable[[], None] | None = None,
) -> None:
```

Inside the function, after `bar.addAction(submodule_action)`, add:
```python
    worktrees_action = QAction("&Worktrees...", window)
    def _open_worktrees() -> None:
        if queries is None or commands is None or on_open_worktrees_dialog is None:
            return
        on_open_worktrees_dialog()
    worktrees_action.triggered.connect(_open_worktrees)
    git_menu.addAction(worktrees_action)
    window._git_worktrees_action = worktrees_action  # type: ignore[attr-defined]
```

- [ ] **Step 2: Update call sites to pass the new callback**

Edit `git_gui/presentation/main_window/repo_lifecycle.py`. In `_on_repo_ready`, change the `install_git_menu(...)` call to:
```python
        install_git_menu(
            self,
            queries=self._queries,
            commands=self._commands,
            repo_workdir=self._repo_path,
            on_open_submodule=self._on_submodule_open_requested,
            on_open_worktrees_dialog=self._open_worktrees_dialog,
        )
```

In `_enter_empty_state`, similarly:
```python
        install_git_menu(
            self,
            queries=None,
            commands=None,
            repo_workdir=None,
            on_open_submodule=self._on_submodule_open_requested,
            on_open_worktrees_dialog=None,
        )
```

(`self._open_worktrees_dialog` will be wired in Task 17.)

- [ ] **Step 3: Verify no menu-tests break**

Run: `uv run pytest tests/presentation/menus/ -v`
Expected: green (action set may be checked — if there's an "action list" assertion, update it to include `Worktrees...`).

- [ ] **Step 4: Commit**

```bash
rtk git add git_gui/presentation/menus/git_menu.py git_gui/presentation/main_window/repo_lifecycle.py
rtk git commit -m "presentation(menu): add Git → Worktrees… action"
```

---

## Task 17: MainWindow wiring — orchestrate the new flows

Bring everything together. This task adds the orchestration code in `MainWindow` / `repo_lifecycle.py` that:
1. After repo load, queries `list_worktrees` and pushes them into `_repo_list.set_active_worktrees` and into sidebar/branches-dialog branch indicators.
2. Listens for `worktree_action_requested` from `_repo_list` (add/manage/open/lock/unlock/remove) and dispatches each.
3. Connects `checkout_in_new_worktree_requested` from sidebar, graph, and branches dialog → opens `AddWorktreeDialog`.
4. Instantiates `SmartCheckout` and routes branch checkouts through it.
5. Provides `_open_worktrees_dialog` (used by the menu callback).
6. Runs add/remove/lock/unlock commands on background threads using the existing `_RemoteSignals`-style pattern, and shows the two-stage remove flow on `WorktreeDirtyError` / `WorktreeLockedError`.

This is the longest single task. It's split into focused steps.

**Files:**
- Modify: `git_gui/presentation/main_window/main_window.py`
- Modify: `git_gui/presentation/main_window/repo_lifecycle.py`

- [ ] **Step 1: Add the worktree-signal carrier**

In `git_gui/presentation/main_window/repo_lifecycle.py`, near the existing `_RepoReadySignals` class, add:
```python
class _WorktreeOpSignals(QObject):
    succeeded = Signal()
    dirty_error = Signal(str)    # path
    locked_error = Signal(str, str)  # path, reason
    failed = Signal(str)         # error message
    added = Signal(str, bool)    # new worktree path, switch_after
```

- [ ] **Step 2: Add a `_load_worktrees_for_active_repo` helper**

In `repo_lifecycle.py`, inside `RepoLifecycleMixin`, add a method that runs after repo-ready to query worktrees and push them to widgets:
```python
    def _load_worktrees_for_active_repo(self) -> None:
        if self._queries is None or self._repo_path is None:
            return
        try:
            wts = self._queries.list_worktrees.execute()
        except Exception as e:
            self._log_panel.log_error(f"Failed to list worktrees: {e}")
            wts = []
        self._repo_list.set_active_worktrees(wts)
        self._repo_list.reload()
        # Push branch-aware data to the in-repo sidebar and the Branches dialog state.
        wt_branches = {wt.branch for wt in wts if wt.branch and not wt.is_main}
        wt_paths = {wt.branch: str(wt.path) for wt in wts if wt.branch and not wt.is_main}
        if hasattr(self._sidebar, "set_worktree_branches"):
            self._sidebar.set_worktree_branches(wt_branches)
        self._worktree_paths_by_branch = wt_paths
```

Call it from the end of `_on_repo_ready`:
```python
        self._load_worktrees_for_active_repo()
```

- [ ] **Step 3: Wire `_repo_list.worktree_action_requested`**

In `repo_lifecycle.py`'s `_wire_repo_lifecycle_signals`, add:
```python
        self._repo_list.worktree_action_requested.connect(self._on_worktree_action)
```

Add the dispatcher method in `RepoLifecycleMixin`:
```python
    def _on_worktree_action(self, action: str, path: str) -> None:
        if action == "add":
            self._open_add_worktree_dialog(preselect_branch=None, default_create=False)
        elif action == "manage":
            self._open_worktrees_dialog()
        elif action == "open":
            self._switch_repo(path)
        elif action == "lock":
            self._run_lock_worktree(path)
        elif action == "unlock":
            self._run_unlock_worktree(path)
        elif action == "remove":
            self._begin_remove_worktree(path)
```

- [ ] **Step 4: Implement the dialog openers**

Still in `repo_lifecycle.py`:
```python
    def _open_add_worktree_dialog(
        self,
        *,
        preselect_branch: str | None,
        default_create: bool,
    ) -> None:
        if self._queries is None or self._commands is None or self._repo_path is None:
            return
        from git_gui.presentation.dialogs.add_worktree_dialog import AddWorktreeDialog
        try:
            branches = [b.name for b in self._queries.get_branches.execute() if not b.is_remote]
        except Exception:
            branches = []
        in_use: dict[str, str] = {}
        try:
            for wt in self._queries.list_worktrees.execute():
                if wt.branch and not wt.is_main:
                    in_use[wt.branch] = str(wt.path)
        except Exception:
            pass
        dlg = AddWorktreeDialog(
            repo_path=self._repo_path,
            branches=branches,
            branches_in_use=in_use,
            preselect_branch=preselect_branch,
            default_create_new=default_create,
            parent=self,
        )
        dlg.add_requested.connect(self._on_add_worktree_requested)
        dlg.switch_to_existing_requested.connect(self._switch_repo)
        dlg.exec()

    def _open_worktrees_dialog(self) -> None:
        if self._queries is None or self._commands is None:
            return
        from git_gui.presentation.dialogs.worktrees_dialog import WorktreesDialog
        try:
            wts = self._queries.list_worktrees.execute()
        except Exception as e:
            self._log_panel.log_error(f"Failed to list worktrees: {e}")
            return
        dlg = WorktreesDialog(worktrees=wts, parent=self)
        dlg.open_requested.connect(self._switch_repo)
        dlg.remove_requested.connect(self._begin_remove_worktree)
        dlg.lock_requested.connect(self._run_lock_worktree_with_reason)
        dlg.unlock_requested.connect(self._run_unlock_worktree)
        dlg.add_requested.connect(lambda: self._open_add_worktree_dialog(
            preselect_branch=None, default_create=False))
        dlg.exec()
```

- [ ] **Step 5: Implement the background workers**

Still in `repo_lifecycle.py`:
```python
    def _on_add_worktree_requested(self, payload: dict) -> None:
        if self._commands is None:
            return
        signals = _WorktreeOpSignals(self)

        def _worker():
            from pathlib import Path
            try:
                wt = self._commands.add_worktree.execute(
                    Path(payload["location"]),
                    payload["branch"],
                    create_branch=payload["create_new"],
                    base_ref=payload["base_ref"],
                )
                signals.added.emit(str(wt.path), payload["switch_after"])
            except Exception as e:
                signals.failed.emit(str(e))

        signals.added.connect(self._on_worktree_added)
        signals.failed.connect(lambda msg: self._log_panel.log_error(f"Add worktree failed: {msg}"))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_worktree_added(self, path: str, switch_after: bool) -> None:
        self._load_worktrees_for_active_repo()
        if switch_after:
            self._switch_repo(path)

    def _run_lock_worktree_with_reason(self, path: str, reason: str) -> None:
        from pathlib import Path
        def _worker():
            try:
                self._commands.lock_worktree.execute(Path(path), reason=reason or None)
            except Exception as e:
                self._log_panel.log_error(f"Lock worktree failed: {e}")
            self._load_worktrees_for_active_repo()
        threading.Thread(target=_worker, daemon=True).start()

    def _run_lock_worktree(self, path: str) -> None:
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Lock Worktree", "Reason (optional):")
        if not ok:
            return
        self._run_lock_worktree_with_reason(path, text.strip())

    def _run_unlock_worktree(self, path: str) -> None:
        from pathlib import Path
        def _worker():
            try:
                self._commands.unlock_worktree.execute(Path(path))
            except Exception as e:
                self._log_panel.log_error(f"Unlock worktree failed: {e}")
            self._load_worktrees_for_active_repo()
        threading.Thread(target=_worker, daemon=True).start()
```

- [ ] **Step 6: Implement the two-stage remove flow**

```python
    def _begin_remove_worktree(self, path: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(
            self, "Remove worktree", f"Remove worktree at {path}?"
        ) != QMessageBox.Yes:
            return
        self._run_remove_worktree(path, force=False)

    def _run_remove_worktree(self, path: str, *, force: bool) -> None:
        from pathlib import Path
        from git_gui.infrastructure.worktree_cli import (
            WorktreeDirtyError, WorktreeLockedError, WorktreeCommandError,
        )
        signals = _WorktreeOpSignals(self)
        def _worker():
            try:
                self._commands.remove_worktree.execute(Path(path), force=force)
                signals.succeeded.emit()
            except WorktreeDirtyError as e:
                signals.dirty_error.emit(path)
            except WorktreeLockedError as e:
                # Extract the reason from the error message if present.
                signals.locked_error.emit(path, str(e))
            except (WorktreeCommandError, Exception) as e:
                signals.failed.emit(str(e))
        signals.succeeded.connect(self._on_worktree_removed)
        signals.dirty_error.connect(self._on_remove_dirty)
        signals.locked_error.connect(self._on_remove_locked)
        signals.failed.connect(lambda msg: self._log_panel.log_error(f"Remove worktree failed: {msg}"))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_worktree_removed(self) -> None:
        # If the active repo IS the removed worktree, switch back to its parent (best effort).
        self._load_worktrees_for_active_repo()

    def _on_remove_dirty(self, path: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("Worktree is dirty")
        msg.setText(f"The worktree at {path} has uncommitted changes.\nForce remove anyway?")
        force = msg.addButton("Force remove", QMessageBox.DestructiveRole)
        msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.exec()
        if msg.clickedButton() is force:
            self._run_remove_worktree(path, force=True)

    def _on_remove_locked(self, path: str, reason: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("Worktree is locked")
        msg.setText(f"The worktree at {path} is locked.\n{reason}\n\nForce remove anyway?")
        force = msg.addButton("Force remove", QMessageBox.DestructiveRole)
        msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.exec()
        if msg.clickedButton() is force:
            self._run_remove_worktree(path, force=True)
```

- [ ] **Step 7: Smart-checkout wiring**

Edit `git_gui/presentation/main_window/main_window.py`. After the buses are constructed, instantiate `SmartCheckout`:
```python
        from git_gui.presentation.services.smart_checkout import SmartCheckout
        self._smart_checkout = SmartCheckout(
            checkout=self._commands.checkout if self._commands else None,
            finder=self._queries.find_worktree_for_branch if self._queries else None,
            parent=self,
        )
        self._smart_checkout.switch_to_worktree_requested.connect(self._switch_repo)
```

In `_on_repo_ready`, after the bus reassignments, rebuild the SmartCheckout to bind to the new buses:
```python
        self._smart_checkout = SmartCheckout(
            checkout=self._commands.checkout,
            finder=self._queries.find_worktree_for_branch,
            parent=self,
        )
        self._smart_checkout.switch_to_worktree_requested.connect(self._switch_repo)
```

Where existing code calls `self._commands.checkout.execute(branch)`, change it to `self._smart_checkout.execute(branch)`. Search the codebase:
Run: `rtk grep "commands.checkout.execute" git_gui/`

For every call site, decide whether it's a "user branch checkout" (route through smart-checkout) or a "commit checkout" / "remote-branch checkout" (leave alone — those don't collide with worktrees the same way). Branch-name checkout → smart_checkout. Replace with `self._smart_checkout.execute(...)` where appropriate.

- [ ] **Step 8: Connect new `checkout_in_new_worktree_requested` signals**

In `repo_lifecycle.py`'s signal-wiring section, when the sidebar, graph, and BranchesDialog are created/refreshed, connect their `checkout_in_new_worktree_requested` to:
```python
        self._sidebar.checkout_in_new_worktree_requested.connect(
            lambda branch: self._open_add_worktree_dialog(preselect_branch=branch, default_create=False)
        )
        self._graph.checkout_in_new_worktree_requested.connect(
            lambda branch: self._open_add_worktree_dialog(preselect_branch=branch, default_create=False)
        )
```

For the BranchesDialog, the connection happens where the dialog is instantiated (likely already in `git_menu.py` or a `branches_dialog` opener inside the main window). Find the instantiation and add:
```python
        d.checkout_in_new_worktree_requested.connect(
            lambda branch: self._open_add_worktree_dialog(preselect_branch=branch, default_create=False)
        )
```

If the dialog is constructed inside `git_menu.py`, refactor to either:
(a) emit the signal up to MainWindow via a new menu callback, or
(b) push the worktree-paths set into the dialog at construction via a callback.

Option (a) is cleaner: extend `install_git_menu` signature with `on_branches_dialog_opened: Callable[[BranchesDialog], None] | None = None` and call it in `_open_branches` after construction.

- [ ] **Step 9: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: all green. Existing checkout-related tests should still pass because `SmartCheckout` is a transparent wrapper for the non-collision path.

If any test fails because it mocks `self._commands.checkout` and the code now calls `self._smart_checkout`, update the test to mock `self._smart_checkout` instead (or to construct the real `SmartCheckout` with the mocked checkout).

- [ ] **Step 10: Commit**

```bash
rtk git add git_gui/presentation/main_window/ git_gui/presentation/menus/git_menu.py
rtk git commit -m "presentation(main_window): wire worktree dialogs, add/remove flows, smart-checkout"
```

---

## Task 18: Manual verification + README update

Last step. Run the app, walk through each user-facing path, then update the README.

- [ ] **Step 1: Launch the app**

Run: `uv run python main.py`

- [ ] **Step 2: Verify each path**

Use a real test repo (e.g. `/tmp/gitcrisp-wt-demo` initialised with `git init` and one commit). For each item, perform the action and confirm the expected outcome.

- [ ] Open the demo repo in GitCrisp.
- [ ] Right-click the repo row in the sidebar → "Add Worktree…" opens the dialog.
- [ ] Branch combo populates; "Create new branch" checkbox toggles into name + base-ref fields; the Location field auto-fills with `{repo_parent}/{repo_name}-{branch}`.
- [ ] Click Add → the worktree directory is created; the new worktree appears as a child of the parent repo in the sidebar.
- [ ] Click the worktree child row → the window switches to that worktree's view (working tree, branch context, etc.).
- [ ] Switch back to the parent.
- [ ] In another terminal, run `git -C /tmp/gitcrisp-wt-demo worktree add /tmp/gitcrisp-wt-demo-ext ext-branch` (create `ext-branch` first if needed). Within ~2 seconds, the new worktree appears in the sidebar.
- [ ] From the Branches dialog, try checking out the branch that lives in the worktree → the window switches to that worktree (smart-checkout). A status-line message confirms.
- [ ] Right-click a worktree child → Remove… → first confirm; if you have uncommitted changes, the force prompt appears; force-remove succeeds.
- [ ] Lock a worktree with a reason ("test lock") → the row shows the lock icon (or "Locked" indicator); tooltip shows the reason.
- [ ] Open the Manage Worktrees dialog from `Git → Worktrees…` → all worktrees appear, lock/unlock/remove buttons work.
- [ ] Verify both light and dark themes — switch from `View → Appearance…` and confirm all new UI uses theme tokens (no contrast issues, no hard-coded colors visible).

If any path fails, file a follow-up entry in `docs/superpowers/follow-ups/` and either fix in a quick patch or note as a known issue.

- [ ] **Step 3: Update the README**

Edit `README.md`. Under the existing "Multi-Repository" section (or as a new section between "Multi-Repository" and "Theming"), add:

```markdown
### Worktrees
- List, add, lock/unlock, and remove `git worktree` instances from inside GitCrisp
- Worktrees appear nested under their parent repo in the sidebar; click to switch
- **Smart checkout** — picking a branch already checked out in another worktree transparently switches to that worktree instead of erroring
- **Add Worktree dialog** — branch combo with disabled state for already-used branches, "Create new branch" toggle with base-ref picker, templated default path (`{repo_parent}/{repo_name}-{branch}`)
- **Two-stage remove** — confirm, then a force prompt if the worktree is dirty or locked
- `Git → Worktrees…` opens the manage dialog with all worktrees and their lock state
- Branches that own a worktree show a `+` badge in the sidebar branch tree and Branches dialog; "Checkout in New Worktree…" is offered in the branch context menus (sidebar, graph, dialog)
```

- [ ] **Step 4: Commit**

```bash
rtk git add README.md
rtk git commit -m "docs(readme): document worktree support"
```

- [ ] **Step 5: Final full-suite check**

Run: `uv run pytest tests/ -v`
Expected: all green.

Then verify the linting (if a script exists) or simply check for obvious errors:
Run: `uv run python -c "import git_gui.presentation.main_window.main_window; print('ok')"`
Expected: `ok`.

---

## Done criteria

- All 18 tasks above are checked off with green tests.
- Manual verification of all user paths passes on both light and dark themes.
- README documents the feature.
- No new hard-coded color values anywhere in the new widgets (all roles via theme tokens).
- The full pytest suite passes.

If any test was skipped or any path failed, drop a follow-up in `docs/superpowers/follow-ups/2026-05-23-worktree-followups.md` so it's tracked instead of forgotten.
