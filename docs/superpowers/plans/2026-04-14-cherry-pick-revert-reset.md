# Cherry-pick, Revert, and Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three commit-level Git operations — cherry-pick, revert, and reset — triggered from the graph's commit context menu in GitStack.

**Architecture:** Clean Architecture layers extended in lockstep. Reset uses pygit2's native `Repository.reset`; cherry-pick and revert shell out to `git` via a new `CommitOpsCli` adapter because pygit2 doesn't accept a mainline parameter for merge commits. A new `ResetDialog` confirms the mode (soft/mixed/hard) with a dirty-file preview for hard resets. The existing conflict banner extends two more state branches (`CHERRY_PICKING` / `REVERTING`) with matching abort/continue routing.

**Tech Stack:** Python 3.13, PySide6 (Qt), pygit2, subprocess (for git CLI), pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-14-cherry-pick-revert-reset-design.md`

---

## File Structure

**New files:**
- `git_gui/infrastructure/commit_ops_cli.py` — `CommitOpsCli` subprocess wrapper for `git cherry-pick` / `git revert`.
- `git_gui/presentation/dialogs/reset_dialog.py` — `ResetDialog` modal.
- `tests/infrastructure/test_commit_ops_cli.py`
- `tests/infrastructure/test_pygit2_repo_reset.py`
- `tests/application/test_commands_cherry_pick_revert_reset.py`
- `tests/presentation/dialogs/test_reset_dialog.py`

**Modified files:**
- `git_gui/domain/entities.py` — add `ResetMode` enum.
- `git_gui/domain/ports.py` — add 7 methods to `IRepositoryWriter`.
- `git_gui/application/commands.py` — add 7 use-case classes.
- `git_gui/infrastructure/pygit2_repo.py` — add 7 writer implementations (5 delegate to `CommitOpsCli`, 1 native reset, 1 is `cherry_pick` passes a flag computed from parents).
- `git_gui/presentation/bus.py` — register 7 new commands.
- `git_gui/presentation/widgets/graph.py` — add signals + menu entries (Cherry-pick, Revert, Reset submenu).
- `git_gui/presentation/widgets/working_tree.py` — extend `update_conflict_banner` for CHERRY_PICKING/REVERTING + 4 new signals + `_on_abort_clicked` / `_on_commit` routing.
- `git_gui/presentation/widgets/diff.py` — extend `update_state_banner` for CHERRY_PICKING/REVERTING + 4 new signals + `_on_banner_abort` / `_on_banner_continue` routing.
- `git_gui/presentation/main_window.py` — wire 3 new graph signals + 4 new banner signals; implement 7 new handler methods.
- `tests/presentation/widgets/test_graph_context_menu.py` — add cases for the 3 new entries.
- `tests/presentation/widgets/test_working_tree_banner.py` — add cases for CHERRY_PICKING / REVERTING.

---

## Task 1: Add ResetMode enum to domain

**Files:**
- Modify: `git_gui/domain/entities.py` (after `MergeStrategy`, ~line 113)

- [ ] **Step 1: Add the enum**

In `git_gui/domain/entities.py`, immediately after the `MergeStrategy` enum block, add:

```python
class ResetMode(str, Enum):
    SOFT = "SOFT"
    MIXED = "MIXED"
    HARD = "HARD"
```

- [ ] **Step 2: Run existing tests to confirm nothing broke**

Run: `uv run pytest tests/ -q`
Expected: all existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add git_gui/domain/entities.py
git commit -m "feat(domain): add ResetMode enum"
```

---

## Task 2: Add writer port methods

**Files:**
- Modify: `git_gui/domain/ports.py`

- [ ] **Step 1: Update imports**

In `git_gui/domain/ports.py:4`, add `ResetMode` to the import:

```python
from git_gui.domain.entities import Branch, Commit, CommitStat, FileStatus, Hunk, LocalBranchInfo, MergeAnalysisResult, MergeStrategy, Remote, RepoStateInfo, ResetMode, Stash, Submodule, Tag
```

- [ ] **Step 2: Add 7 method signatures to `IRepositoryWriter`**

Append these lines inside the `IRepositoryWriter` Protocol (after `interactive_rebase` at line 81):

```python
    def cherry_pick(self, oid: str) -> None: ...
    def revert_commit(self, oid: str) -> None: ...
    def reset_to(self, oid: str, mode: ResetMode) -> None: ...
    def cherry_pick_abort(self) -> None: ...
    def cherry_pick_continue(self) -> None: ...
    def revert_abort(self) -> None: ...
    def revert_continue(self) -> None: ...
```

- [ ] **Step 3: Run tests to confirm the protocol still type-checks via `runtime_checkable`**

Run: `uv run pytest tests/ -q`
Expected: all existing tests pass (there will be a fleeting mismatch with `Pygit2Repository` once it's type-checked, but because `Protocol` is structural, tests will still pass — we'll add implementations next).

- [ ] **Step 4: Commit**

```bash
git add git_gui/domain/ports.py
git commit -m "feat(domain): add cherry_pick/revert/reset ports"
```

---

## Task 3: CommitOpsCli subprocess adapter — tests

**Files:**
- Test: `tests/infrastructure/test_commit_ops_cli.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/infrastructure/test_commit_ops_cli.py`:

```python
from __future__ import annotations
import os
import subprocess
from pathlib import Path
import pytest

from git_gui.infrastructure.commit_ops_cli import CommitOpsCli


def _run(cwd: str, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _commit(cwd: Path, filename: str, content: str, msg: str) -> str:
    (cwd / filename).write_text(content)
    _run(str(cwd), "add", "-A")
    _run(str(cwd), "commit", "-m", msg)
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(cwd),
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


@pytest.fixture
def linear_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """master with 3 commits. Returns (path, base_sha, tip_sha)."""
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    base = _commit(tmp_path, "a.txt", "a\n", "add a")
    _commit(tmp_path, "b.txt", "b\n", "add b")
    tip = _commit(tmp_path, "c.txt", "c\n", "add c")
    return tmp_path, base, tip


def test_cherry_pick_non_merge_applies_commit_to_head(linear_repo, tmp_path):
    repo_path, _base, _tip = linear_repo
    # Create a branch off base, cherry-pick the tip onto it.
    _run(str(repo_path), "checkout", "-q", "-b", "feature", _base)
    # Cherry-pick: pick the top-of-master commit onto feature.
    # First we need a non-conflicting commit — use the tip which adds c.txt.
    tip_on_master = subprocess.run(
        ["git", "rev-parse", "master"], cwd=str(repo_path),
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    cli = CommitOpsCli(str(repo_path))
    cli.cherry_pick(tip_on_master, is_merge=False)

    assert (repo_path / "c.txt").exists()
    # HEAD is now a new commit on feature, not tip_on_master itself.
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_path),
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert head != tip_on_master


def test_cherry_pick_invalid_sha_raises(linear_repo):
    repo_path, _base, _tip = linear_repo
    cli = CommitOpsCli(str(repo_path))
    with pytest.raises(RuntimeError):
        cli.cherry_pick("0000000000000000000000000000000000000000", is_merge=False)


def test_cherry_pick_conflict_does_not_raise(tmp_path: Path):
    """A cherry-pick that conflicts leaves state on disk; the CLI must not raise."""
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "line1\n", "init")
    _run(str(tmp_path), "checkout", "-q", "-b", "a")
    conflict_sha = _commit(tmp_path, "f.txt", "from-a\n", "from a")
    _run(str(tmp_path), "checkout", "-q", "master")
    _commit(tmp_path, "f.txt", "from-master\n", "from master")

    cli = CommitOpsCli(str(tmp_path))
    cli.cherry_pick(conflict_sha, is_merge=False)  # Must not raise.
    assert (tmp_path / ".git" / "CHERRY_PICK_HEAD").exists()


def test_cherry_pick_merge_commit_with_is_merge_true(tmp_path: Path):
    """Cherry-picking a merge commit requires -m; is_merge=True passes it."""
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "base.txt", "base\n", "base")
    _run(str(tmp_path), "checkout", "-q", "-b", "feature")
    _commit(tmp_path, "feat.txt", "feat\n", "feat")
    _run(str(tmp_path), "checkout", "-q", "master")
    _commit(tmp_path, "other.txt", "other\n", "other")
    # Create a merge commit on master.
    _run(str(tmp_path), "merge", "--no-ff", "-m", "merge feature", "feature")
    merge_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(tmp_path),
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    # Now reset master to before the merge and cherry-pick the merge commit.
    _run(str(tmp_path), "reset", "--hard", "HEAD~1")
    # Create a new branch that doesn't have the merge commit yet.
    _run(str(tmp_path), "checkout", "-q", "-b", "target")

    cli = CommitOpsCli(str(tmp_path))
    cli.cherry_pick(merge_sha, is_merge=True)  # Must succeed with -m 1.

    assert (tmp_path / "feat.txt").exists()  # first-parent side was master, so -m 1 picks "feature" additions


def test_revert_commit_non_merge(linear_repo):
    repo_path, _base, tip = linear_repo
    cli = CommitOpsCli(str(repo_path))
    cli.revert_commit(tip, is_merge=False)
    assert not (repo_path / "c.txt").exists()  # the file added in `tip` is removed by the revert


def test_revert_commit_conflict_does_not_raise(tmp_path: Path):
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "line1\n", "init")
    target = _commit(tmp_path, "f.txt", "line2\n", "update")
    _commit(tmp_path, "f.txt", "line3\n", "second update")

    cli = CommitOpsCli(str(tmp_path))
    cli.revert_commit(target, is_merge=False)  # Conflict; must not raise.
    assert (tmp_path / ".git" / "REVERT_HEAD").exists()


def test_cherry_pick_abort(tmp_path: Path):
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "line1\n", "init")
    _run(str(tmp_path), "checkout", "-q", "-b", "a")
    conflict_sha = _commit(tmp_path, "f.txt", "from-a\n", "from a")
    _run(str(tmp_path), "checkout", "-q", "master")
    _commit(tmp_path, "f.txt", "from-master\n", "from master")

    cli = CommitOpsCli(str(tmp_path))
    cli.cherry_pick(conflict_sha, is_merge=False)
    assert (tmp_path / ".git" / "CHERRY_PICK_HEAD").exists()
    cli.cherry_pick_abort()
    assert not (tmp_path / ".git" / "CHERRY_PICK_HEAD").exists()


def test_revert_abort(tmp_path: Path):
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "line1\n", "init")
    target = _commit(tmp_path, "f.txt", "line2\n", "update")
    _commit(tmp_path, "f.txt", "line3\n", "second update")

    cli = CommitOpsCli(str(tmp_path))
    cli.revert_commit(target, is_merge=False)
    assert (tmp_path / ".git" / "REVERT_HEAD").exists()
    cli.revert_abort()
    assert not (tmp_path / ".git" / "REVERT_HEAD").exists()


def test_cherry_pick_continue_after_resolution(tmp_path: Path):
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "line1\n", "init")
    _run(str(tmp_path), "checkout", "-q", "-b", "a")
    conflict_sha = _commit(tmp_path, "f.txt", "from-a\n", "from a")
    _run(str(tmp_path), "checkout", "-q", "master")
    _commit(tmp_path, "f.txt", "from-master\n", "from master")

    cli = CommitOpsCli(str(tmp_path))
    cli.cherry_pick(conflict_sha, is_merge=False)
    # Resolve by taking theirs.
    (tmp_path / "f.txt").write_text("from-a\n")
    _run(str(tmp_path), "add", "f.txt")
    cli.cherry_pick_continue()
    assert not (tmp_path / ".git" / "CHERRY_PICK_HEAD").exists()


def test_revert_continue_after_resolution(tmp_path: Path):
    _run(str(tmp_path), "init", "-q", "-b", "master")
    _run(str(tmp_path), "config", "user.email", "t@t")
    _run(str(tmp_path), "config", "user.name", "t")
    _commit(tmp_path, "f.txt", "line1\n", "init")
    target = _commit(tmp_path, "f.txt", "line2\n", "update")
    _commit(tmp_path, "f.txt", "line3\n", "second update")

    cli = CommitOpsCli(str(tmp_path))
    cli.revert_commit(target, is_merge=False)
    (tmp_path / "f.txt").write_text("resolved\n")
    _run(str(tmp_path), "add", "f.txt")
    cli.revert_continue()
    assert not (tmp_path / ".git" / "REVERT_HEAD").exists()
```

- [ ] **Step 2: Run to verify the tests fail**

Run: `uv run pytest tests/infrastructure/test_commit_ops_cli.py -v`
Expected: all tests fail with `ModuleNotFoundError: No module named 'git_gui.infrastructure.commit_ops_cli'`.

---

## Task 4: CommitOpsCli subprocess adapter — implementation

**Files:**
- Create: `git_gui/infrastructure/commit_ops_cli.py`

- [ ] **Step 1: Write the implementation**

Create `git_gui/infrastructure/commit_ops_cli.py`:

```python
from __future__ import annotations
import os
import shutil
import subprocess

from git_gui.resources import subprocess_kwargs


class CommitOpsCommandError(Exception):
    """Raised when a git cherry-pick / revert CLI call fails unexpectedly."""


class CommitOpsCli:
    """Thin wrapper around `git cherry-pick` and `git revert` via subprocess.

    pygit2 does not accept a mainline (`-m`) argument for cherry-picking or
    reverting a merge commit, so we shell out to the `git` CLI. Conflict exits
    are swallowed: the repo is left in CHERRY_PICK_HEAD / REVERT_HEAD state
    and the caller surfaces the banner on the next reload.
    """

    def __init__(self, repo_workdir: str, git_executable: str = "git") -> None:
        self._cwd = repo_workdir
        self._git = git_executable

    def cherry_pick(self, oid: str, is_merge: bool) -> None:
        argv = ["cherry-pick"]
        if is_merge:
            argv += ["-m", "1"]
        argv.append(oid)
        self._run(argv)

    def revert_commit(self, oid: str, is_merge: bool) -> None:
        argv = ["revert", "--no-edit"]
        if is_merge:
            argv += ["-m", "1"]
        argv.append(oid)
        self._run(argv)

    def cherry_pick_abort(self) -> None:
        self._run(["cherry-pick", "--abort"])

    def cherry_pick_continue(self) -> None:
        self._run(["cherry-pick", "--continue"], env_overrides={"GIT_EDITOR": "true"})

    def revert_abort(self) -> None:
        self._run(["revert", "--abort"])

    def revert_continue(self) -> None:
        self._run(["revert", "--continue"], env_overrides={"GIT_EDITOR": "true"})

    def _run(self, argv: list[str], env_overrides: dict[str, str] | None = None) -> None:
        if shutil.which(self._git) is None:
            raise CommitOpsCommandError(f"`{self._git}` executable not found on PATH")
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        try:
            result = subprocess.run(
                [self._git, *argv],
                cwd=self._cwd,
                capture_output=True,
                text=True,
                env=env,
                **subprocess_kwargs(),
            )
        except FileNotFoundError as e:
            raise CommitOpsCommandError(
                f"`{self._git}` executable not found on PATH"
            ) from e
        if result.returncode == 0:
            return
        if self._is_conflict_exit(result):
            return
        stderr = (result.stderr or "").strip() or (result.stdout or "").strip() or f"exit code {result.returncode}"
        raise RuntimeError(stderr)

    @staticmethod
    def _is_conflict_exit(result: subprocess.CompletedProcess) -> bool:
        output = ((result.stderr or "") + (result.stdout or "")).lower()
        return "conflict" in output or "after resolving the conflicts" in output
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/infrastructure/test_commit_ops_cli.py -v`
Expected: all 11 tests pass.

- [ ] **Step 3: Commit**

```bash
git add git_gui/infrastructure/commit_ops_cli.py tests/infrastructure/test_commit_ops_cli.py
git commit -m "feat(infra): add CommitOpsCli adapter for git cherry-pick / revert"
```

---

## Task 5: pygit2_repo.reset_to — tests

**Files:**
- Test: `tests/infrastructure/test_pygit2_repo_reset.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/infrastructure/test_pygit2_repo_reset.py`:

```python
from __future__ import annotations
import subprocess
from pathlib import Path
import pytest
import pygit2

from git_gui.domain.entities import ResetMode
from git_gui.infrastructure.pygit2_repo import Pygit2Repository


@pytest.fixture
def three_commit_repo(tmp_path: Path) -> tuple[Pygit2Repository, str, str, str]:
    """master with 3 commits. Returns (impl, first_sha, second_sha, third_sha)."""
    def _run(*args):
        subprocess.run(["git", *args], cwd=str(tmp_path), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    _run("init", "-q", "-b", "master")
    _run("config", "user.email", "t@t")
    _run("config", "user.name", "t")

    def _commit(name: str, content: str, msg: str) -> str:
        (tmp_path / name).write_text(content)
        _run("add", name)
        _run("commit", "-m", msg)
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(tmp_path),
            capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()

    first = _commit("a.txt", "a\n", "first")
    second = _commit("b.txt", "b\n", "second")
    third = _commit("c.txt", "c\n", "third")
    return Pygit2Repository(str(tmp_path)), first, second, third


def _head_sha(repo_path: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_path),
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def test_reset_soft_moves_head_only(three_commit_repo, tmp_path):
    impl, first, _second, _third = three_commit_repo
    impl.reset_to(first, ResetMode.SOFT)
    # HEAD is now first; index still has b.txt and c.txt staged.
    assert _head_sha(tmp_path) == first
    # Working tree untouched.
    assert (tmp_path / "b.txt").exists()
    assert (tmp_path / "c.txt").exists()
    # Both files are staged (index entries for them).
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(tmp_path),
        capture_output=True, text=True, check=True,
    ).stdout
    assert "A  b.txt" in status
    assert "A  c.txt" in status


def test_reset_mixed_keeps_working_tree_resets_index(three_commit_repo, tmp_path):
    impl, first, _second, _third = three_commit_repo
    impl.reset_to(first, ResetMode.MIXED)
    assert _head_sha(tmp_path) == first
    assert (tmp_path / "b.txt").exists()
    assert (tmp_path / "c.txt").exists()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(tmp_path),
        capture_output=True, text=True, check=True,
    ).stdout
    # Now b.txt / c.txt are untracked (??), not staged.
    assert "?? b.txt" in status
    assert "?? c.txt" in status


def test_reset_hard_discards_everything(three_commit_repo, tmp_path):
    impl, first, _second, _third = three_commit_repo
    impl.reset_to(first, ResetMode.HARD)
    assert _head_sha(tmp_path) == first
    assert not (tmp_path / "b.txt").exists()
    assert not (tmp_path / "c.txt").exists()


def test_reset_to_head_is_noop(three_commit_repo, tmp_path):
    impl, _first, _second, third = three_commit_repo
    impl.reset_to(third, ResetMode.HARD)
    assert _head_sha(tmp_path) == third
    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").exists()
    assert (tmp_path / "c.txt").exists()
```

- [ ] **Step 2: Run to verify the tests fail**

Run: `uv run pytest tests/infrastructure/test_pygit2_repo_reset.py -v`
Expected: all 4 tests fail with `AttributeError: 'Pygit2Repository' object has no attribute 'reset_to'`.

---

## Task 6: pygit2_repo writer additions — implementation

**Files:**
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Update imports**

In `git_gui/infrastructure/pygit2_repo.py:14`, add `ResetMode` to the domain entities import:

```python
    Branch, Commit, CommitStat, FileStat, FileStatus, Hunk, LocalBranchInfo, MergeAnalysisResult, MergeStrategy, Remote, RepoState, RepoStateInfo, ResetMode, Stash, Submodule, Tag, WORKING_TREE_OID,
```

And at the top of the file, import `CommitOpsCli`:

```python
from git_gui.infrastructure.commit_ops_cli import CommitOpsCli
```

- [ ] **Step 2: Wire a CommitOpsCli instance into `Pygit2Repository.__init__`**

Find the `__init__` method (search for `def __init__`). Locate the existing submodule CLI instantiation (search for `SubmoduleCli` in the file — it's in `__init__`). Immediately after the `SubmoduleCli` line, add:

```python
        self._commit_ops = CommitOpsCli(self._repo.workdir)
```

- [ ] **Step 3: Add the 7 writer methods**

Append these methods to the `Pygit2Repository` class, immediately after `interactive_rebase` (the last writer method, around line 1180):

```python
    def cherry_pick(self, oid: str) -> None:
        commit = self._repo[pygit2.Oid(hex=oid)]
        is_merge = len(commit.parents) > 1
        self._commit_ops.cherry_pick(oid, is_merge=is_merge)

    def revert_commit(self, oid: str) -> None:
        commit = self._repo[pygit2.Oid(hex=oid)]
        is_merge = len(commit.parents) > 1
        self._commit_ops.revert_commit(oid, is_merge=is_merge)

    def reset_to(self, oid: str, mode: ResetMode) -> None:
        pygit2_type = {
            ResetMode.SOFT: pygit2.GIT_RESET_SOFT,
            ResetMode.MIXED: pygit2.GIT_RESET_MIXED,
            ResetMode.HARD: pygit2.GIT_RESET_HARD,
        }[mode]
        self._repo.reset(pygit2.Oid(hex=oid), pygit2_type)

    def cherry_pick_abort(self) -> None:
        self._commit_ops.cherry_pick_abort()

    def cherry_pick_continue(self) -> None:
        self._commit_ops.cherry_pick_continue()

    def revert_abort(self) -> None:
        self._commit_ops.revert_abort()

    def revert_continue(self) -> None:
        self._commit_ops.revert_continue()
```

- [ ] **Step 4: Run reset tests**

Run: `uv run pytest tests/infrastructure/test_pygit2_repo_reset.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Run full infrastructure test suite to confirm no regressions**

Run: `uv run pytest tests/infrastructure/ -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_pygit2_repo_reset.py
git commit -m "feat(infra): implement cherry_pick/revert/reset_to on Pygit2Repository"
```

---

## Task 7: Application use cases — tests

**Files:**
- Test: `tests/application/test_commands_cherry_pick_revert_reset.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/application/test_commands_cherry_pick_revert_reset.py`:

```python
from unittest.mock import MagicMock

from git_gui.domain.entities import ResetMode
from git_gui.domain.ports import IRepositoryWriter
from git_gui.application.commands import (
    CherryPickCommit, RevertCommit, ResetBranch,
    CherryPickAbort, CherryPickContinue,
    RevertAbort, RevertContinue,
)


def _writer():
    return MagicMock(spec=IRepositoryWriter)


def test_cherry_pick_commit_delegates():
    w = _writer()
    CherryPickCommit(w).execute("abc123")
    w.cherry_pick.assert_called_once_with("abc123")


def test_revert_commit_delegates():
    w = _writer()
    RevertCommit(w).execute("def456")
    w.revert_commit.assert_called_once_with("def456")


def test_reset_branch_delegates_with_mode():
    w = _writer()
    ResetBranch(w).execute("abc123", ResetMode.HARD)
    w.reset_to.assert_called_once_with("abc123", ResetMode.HARD)


def test_reset_branch_mixed_mode():
    w = _writer()
    ResetBranch(w).execute("abc123", ResetMode.MIXED)
    w.reset_to.assert_called_once_with("abc123", ResetMode.MIXED)


def test_cherry_pick_abort_delegates():
    w = _writer()
    CherryPickAbort(w).execute()
    w.cherry_pick_abort.assert_called_once_with()


def test_cherry_pick_continue_delegates():
    w = _writer()
    CherryPickContinue(w).execute()
    w.cherry_pick_continue.assert_called_once_with()


def test_revert_abort_delegates():
    w = _writer()
    RevertAbort(w).execute()
    w.revert_abort.assert_called_once_with()


def test_revert_continue_delegates():
    w = _writer()
    RevertContinue(w).execute()
    w.revert_continue.assert_called_once_with()
```

- [ ] **Step 2: Run to verify tests fail**

Run: `uv run pytest tests/application/test_commands_cherry_pick_revert_reset.py -v`
Expected: `ImportError` — the 7 use-case classes don't exist.

---

## Task 8: Application use cases — implementation

**Files:**
- Modify: `git_gui/application/commands.py`

- [ ] **Step 1: Update imports**

In `git_gui/application/commands.py:2`, add `ResetMode` to the imports:

```python
from git_gui.domain.entities import Branch, Commit, MergeStrategy, ResetMode
```

- [ ] **Step 2: Append 7 new use-case classes**

Append to the end of `git_gui/application/commands.py`:

```python
class CherryPickCommit:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, oid: str) -> None:
        self._writer.cherry_pick(oid)


class RevertCommit:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, oid: str) -> None:
        self._writer.revert_commit(oid)


class ResetBranch:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, oid: str, mode: ResetMode) -> None:
        self._writer.reset_to(oid, mode)


class CherryPickAbort:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self) -> None:
        self._writer.cherry_pick_abort()


class CherryPickContinue:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self) -> None:
        self._writer.cherry_pick_continue()


class RevertAbort:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self) -> None:
        self._writer.revert_abort()


class RevertContinue:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self) -> None:
        self._writer.revert_continue()
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/application/test_commands_cherry_pick_revert_reset.py -v`
Expected: all 8 tests pass.

- [ ] **Step 4: Commit**

```bash
git add git_gui/application/commands.py tests/application/test_commands_cherry_pick_revert_reset.py
git commit -m "feat(application): add cherry-pick/revert/reset use cases"
```

---

## Task 9: Bus registration

**Files:**
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Update the import block**

In `git_gui/presentation/bus.py:14-28`, extend the `from git_gui.application.commands import (...)` statement to include the 7 new classes. Append to the last line before the closing paren:

```python
    CherryPickCommit, RevertCommit, ResetBranch,
    CherryPickAbort, CherryPickContinue,
    RevertAbort, RevertContinue,
```

- [ ] **Step 2: Add 7 dataclass fields to `CommandBus`**

In the `CommandBus` dataclass (starts at line 90), append after `interactive_rebase: InteractiveRebase`:

```python
    cherry_pick: CherryPickCommit
    revert_commit: RevertCommit
    reset_branch: ResetBranch
    cherry_pick_abort: CherryPickAbort
    cherry_pick_continue: CherryPickContinue
    revert_abort: RevertAbort
    revert_continue: RevertContinue
```

- [ ] **Step 3: Construct them in `from_writer`**

In `CommandBus.from_writer` (around line 138), before the closing `)` of the `cls(...)` call, append after `interactive_rebase=InteractiveRebase(writer),`:

```python
            cherry_pick=CherryPickCommit(writer),
            revert_commit=RevertCommit(writer),
            reset_branch=ResetBranch(writer),
            cherry_pick_abort=CherryPickAbort(writer),
            cherry_pick_continue=CherryPickContinue(writer),
            revert_abort=RevertAbort(writer),
            revert_continue=RevertContinue(writer),
```

- [ ] **Step 4: Run the full test suite to catch any wiring errors**

Run: `uv run pytest tests/ -q`
Expected: all existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/bus.py
git commit -m "feat(bus): register cherry-pick/revert/reset commands"
```

---

## Task 10: ResetDialog — tests

**Files:**
- Test: `tests/presentation/dialogs/test_reset_dialog.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/presentation/dialogs/test_reset_dialog.py`:

```python
from __future__ import annotations
import pytest

from git_gui.domain.entities import FileStatus, ResetMode
from git_gui.presentation.dialogs.reset_dialog import ResetDialog


def _status(path: str, code: str = "M") -> FileStatus:
    # FileStatus fields: path, status (e.g. "M", "??", "A"), is_staged, is_conflicted.
    # Minimal constructor — match the actual entity. Use defaults for unused fields.
    return FileStatus(path=path, status=code, is_staged=False, is_conflicted=False)


def test_default_mode_is_mixed(qtbot):
    dlg = ResetDialog("master", "abc1234", "Initial commit",
                      default_mode=ResetMode.MIXED, dirty_files=[])
    qtbot.addWidget(dlg)
    assert dlg._radio_mixed.isChecked()


def test_pre_selected_hard_mode(qtbot):
    dlg = ResetDialog("master", "abc1234", "Initial commit",
                      default_mode=ResetMode.HARD, dirty_files=[])
    qtbot.addWidget(dlg)
    assert dlg._radio_hard.isChecked()


def test_dirty_file_list_hidden_for_soft(qtbot):
    files = [_status("src/foo.py", "M")]
    dlg = ResetDialog("master", "abc1234", "msg",
                      default_mode=ResetMode.SOFT, dirty_files=files)
    qtbot.addWidget(dlg)
    assert dlg._dirty_list.isVisible() is False


def test_dirty_file_list_hidden_for_mixed(qtbot):
    files = [_status("src/foo.py", "M")]
    dlg = ResetDialog("master", "abc1234", "msg",
                      default_mode=ResetMode.MIXED, dirty_files=files)
    qtbot.addWidget(dlg)
    assert dlg._dirty_list.isVisible() is False


def test_dirty_file_list_visible_for_hard(qtbot):
    files = [_status("src/foo.py", "M"), _status("src/new.py", "??")]
    dlg = ResetDialog("master", "abc1234", "msg",
                      default_mode=ResetMode.HARD, dirty_files=files)
    qtbot.addWidget(dlg)
    dlg.show()  # needed for isVisible to report accurately
    assert dlg._dirty_list.isVisible() is True
    text = dlg._dirty_list.toPlainText()
    assert "src/foo.py" in text
    assert "src/new.py" in text


def test_hard_with_clean_tree_shows_clean_message(qtbot):
    dlg = ResetDialog("master", "abc1234", "msg",
                      default_mode=ResetMode.HARD, dirty_files=[])
    qtbot.addWidget(dlg)
    dlg.show()
    assert "clean" in dlg._dirty_list.toPlainText().lower()


def test_switching_to_hard_reveals_dirty_list(qtbot):
    files = [_status("src/foo.py", "M")]
    dlg = ResetDialog("master", "abc1234", "msg",
                      default_mode=ResetMode.MIXED, dirty_files=files)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg._dirty_list.isVisible() is False
    dlg._radio_hard.setChecked(True)
    assert dlg._dirty_list.isVisible() is True


def test_result_mode_returns_selected(qtbot):
    dlg = ResetDialog("master", "abc1234", "msg",
                      default_mode=ResetMode.MIXED, dirty_files=[])
    qtbot.addWidget(dlg)
    dlg._radio_soft.setChecked(True)
    assert dlg.result_mode() == ResetMode.SOFT
    dlg._radio_hard.setChecked(True)
    assert dlg.result_mode() == ResetMode.HARD
```

- [ ] **Step 2: Verify tests fail**

Run: `uv run pytest tests/presentation/dialogs/test_reset_dialog.py -v`
Expected: `ModuleNotFoundError: No module named 'git_gui.presentation.dialogs.reset_dialog'`.

- [ ] **Step 3: Before implementing, check the real `FileStatus` shape**

Run: `uv run python -c "from git_gui.domain.entities import FileStatus; import dataclasses; print(dataclasses.fields(FileStatus))"`
If the field set differs from `(path, status, is_staged, is_conflicted)`, adjust the `_status` helper in the test to match. Common alternatives: single `status` string already combines staged/unstaged info. Correct the test before moving to Step 4.

---

## Task 11: ResetDialog — implementation

**Files:**
- Create: `git_gui/presentation/dialogs/reset_dialog.py`

- [ ] **Step 1: Create the dialog file**

Create `git_gui/presentation/dialogs/reset_dialog.py`:

```python
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QRadioButton,
    QVBoxLayout, QWidget,
)

from git_gui.domain.entities import FileStatus, ResetMode


class ResetDialog(QDialog):
    """Confirm a `git reset` operation: mode radios + dirty-file preview for HARD."""

    def __init__(
        self,
        branch_name: str,
        short_sha: str,
        commit_subject: str,
        default_mode: ResetMode,
        dirty_files: list[FileStatus],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reset Branch")
        self._dirty_files = dirty_files

        layout = QVBoxLayout(self)

        header = QLabel(
            f"Reset <b>{branch_name}</b> to <code>{short_sha}</code> "
            f"&quot;{commit_subject}&quot;"
        )
        header.setTextFormat(header.textFormat().RichText)
        layout.addWidget(header)

        self._radio_soft = QRadioButton("Soft — keep index and working tree")
        self._radio_mixed = QRadioButton("Mixed — keep working tree, reset index")
        self._radio_hard = QRadioButton("Hard — discard all uncommitted changes")
        layout.addWidget(self._radio_soft)
        layout.addWidget(self._radio_mixed)
        layout.addWidget(self._radio_hard)

        {
            ResetMode.SOFT: self._radio_soft,
            ResetMode.MIXED: self._radio_mixed,
            ResetMode.HARD: self._radio_hard,
        }[default_mode].setChecked(True)

        self._dirty_label = QLabel("⚠ The following uncommitted changes will be lost:")
        self._dirty_list = QPlainTextEdit()
        self._dirty_list.setReadOnly(True)
        self._populate_dirty_list()
        layout.addWidget(self._dirty_label)
        layout.addWidget(self._dirty_list)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("Reset")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for radio in (self._radio_soft, self._radio_mixed, self._radio_hard):
            radio.toggled.connect(self._update_dirty_list_visibility)
        self._update_dirty_list_visibility()

    def _populate_dirty_list(self) -> None:
        if not self._dirty_files:
            self._dirty_list.setPlainText("Working tree is clean.")
            return
        lines = []
        for f in self._dirty_files:
            lines.append(f"{f.status}  {f.path}")
        self._dirty_list.setPlainText("\n".join(lines))

    def _update_dirty_list_visibility(self) -> None:
        show = self._radio_hard.isChecked()
        self._dirty_label.setVisible(show)
        self._dirty_list.setVisible(show)

    def result_mode(self) -> ResetMode:
        if self._radio_soft.isChecked():
            return ResetMode.SOFT
        if self._radio_hard.isChecked():
            return ResetMode.HARD
        return ResetMode.MIXED
```

- [ ] **Step 2: Run dialog tests**

Run: `uv run pytest tests/presentation/dialogs/test_reset_dialog.py -v`
Expected: all 8 tests pass. If a test fails because of the `FileStatus` field names, adjust `_populate_dirty_list` to match the actual shape (only `path` is guaranteed; `status` field name may be `index_status`, etc.).

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/dialogs/reset_dialog.py tests/presentation/dialogs/test_reset_dialog.py
git commit -m "feat(dialogs): add ResetDialog"
```

---

## Task 12: Graph context menu — add signals and menu entries

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py`

- [ ] **Step 1: Add 3 new signals to `GraphWidget`**

Find the block of `Signal(...)` declarations in `GraphWidget` (search for `merge_commit_requested = Signal`). Immediately after the last such signal (before any method definition), add:

```python
    cherry_pick_requested = Signal(str)         # oid
    revert_commit_requested = Signal(str)       # oid
    reset_to_commit_requested = Signal(str, object)  # oid, ResetMode
```

The `object` type for the second arg is required because PySide6 signals don't accept arbitrary Python enum types directly.

- [ ] **Step 2: Import `ResetMode` at the top of graph.py**

Near the existing domain imports in `graph.py`, add:

```python
from git_gui.domain.entities import ResetMode
```

(Merge with existing `from git_gui.domain.entities import ...` line if present.)

- [ ] **Step 3: Add menu entries inside `_add_merge_rebase_section`**

At the **end** of `_add_merge_rebase_section` (after the interactive rebase submenu block, around `graph.py:710`), append a new section. Insert right before the function returns:

```python
        # ── Cherry-pick / Revert / Reset section ───────────────────────
        # Only show when we have a HEAD and target != HEAD.
        if head_oid and oid != head_oid:
            menu.addSeparator()

            # Cherry-pick
            cp_action = menu.addAction(f"Cherry-pick commit {short_oid}")
            if global_disable_reason:
                cp_action.setEnabled(False)
                cp_action.setToolTip(global_disable_reason)
            else:
                cp_action.triggered.connect(
                    lambda _checked=False, o=oid: self.cherry_pick_requested.emit(o))

            # Revert
            rv_action = menu.addAction(f"Revert commit {short_oid}")
            if global_disable_reason:
                rv_action.setEnabled(False)
                rv_action.setToolTip(global_disable_reason)
            else:
                rv_action.triggered.connect(
                    lambda _checked=False, o=oid: self.revert_commit_requested.emit(o))

            # Reset — only enabled when target is an ancestor of HEAD.
            can_reset = False
            try:
                can_reset = self._queries.is_ancestor.execute(oid, head_oid)
            except Exception:
                can_reset = False

            reset_sub = menu.addMenu(f"Reset {head_label} to {short_oid}")
            reset_sub.setToolTipsVisible(True)
            modes = [
                (ResetMode.SOFT, "Soft (keep index + working tree)"),
                (ResetMode.MIXED, "Mixed (keep working tree, reset index)"),
                (ResetMode.HARD, "Hard (discard everything)"),
            ]
            for mode, label in modes:
                a = reset_sub.addAction(label)
                if global_disable_reason:
                    a.setEnabled(False)
                    a.setToolTip(global_disable_reason)
                elif not can_reset:
                    a.setEnabled(False)
                    a.setToolTip("Target is not an ancestor of HEAD")
                else:
                    a.triggered.connect(
                        lambda _checked=False, o=oid, m=mode:
                            self.reset_to_commit_requested.emit(o, m))
```

- [ ] **Step 4: Extend the context-menu test**

Open `tests/presentation/widgets/test_graph_context_menu.py`. At the end of the file, append:

```python
from git_gui.domain.entities import ResetMode


def _menu_with_new_section(qtbot, *, state: RepoStateInfo,
                            head_oid: str, target_oid: str,
                            is_ancestor_of_head: bool) -> QMenu:
    queries = _FakeQueryBus(
        state=state,
        head_oid=head_oid,
        is_ancestor=lambda a, d: is_ancestor_of_head if a == target_oid and d == head_oid else False,
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    w._add_merge_rebase_section(menu, target_oid, branches_on_commit=[])
    return menu


def test_cherry_pick_entry_present_and_enabled_when_clean(qtbot):
    state = RepoStateInfo(state=RepoState.CLEAN, head_branch="master")
    menu = _menu_with_new_section(
        qtbot, state=state, head_oid="h" * 40, target_oid="t" * 40,
        is_ancestor_of_head=False,
    )
    actions = _collect_actions(menu)
    texts = [a.text for a in actions]
    assert any("Cherry-pick commit" in t for t in texts)
    cp = next(a for a in actions if a.text.startswith("Cherry-pick"))
    assert cp.enabled is True


def test_cherry_pick_entry_disabled_when_merging(qtbot):
    state = RepoStateInfo(state=RepoState.MERGING, head_branch="master")
    menu = _menu_with_new_section(
        qtbot, state=state, head_oid="h" * 40, target_oid="t" * 40,
        is_ancestor_of_head=False,
    )
    actions = _collect_actions(menu)
    cp = next(a for a in actions if a.text.startswith("Cherry-pick"))
    assert cp.enabled is False


def test_revert_entry_present_and_enabled_when_clean(qtbot):
    state = RepoStateInfo(state=RepoState.CLEAN, head_branch="master")
    menu = _menu_with_new_section(
        qtbot, state=state, head_oid="h" * 40, target_oid="t" * 40,
        is_ancestor_of_head=False,
    )
    actions = _collect_actions(menu)
    rv = next(a for a in actions if a.text.startswith("Revert commit"))
    assert rv.enabled is True


def test_reset_submenu_disabled_when_not_ancestor(qtbot):
    state = RepoStateInfo(state=RepoState.CLEAN, head_branch="master")
    menu = _menu_with_new_section(
        qtbot, state=state, head_oid="h" * 40, target_oid="t" * 40,
        is_ancestor_of_head=False,
    )
    actions = _collect_actions(menu)
    # Any reset submenu entry should be disabled.
    reset_items = [a for a in actions
                   if "keep" in a.text.lower() or "discard" in a.text.lower()]
    assert reset_items  # submenu entries collected
    assert all(not a.enabled for a in reset_items)


def test_reset_submenu_enabled_when_ancestor(qtbot):
    state = RepoStateInfo(state=RepoState.CLEAN, head_branch="master")
    menu = _menu_with_new_section(
        qtbot, state=state, head_oid="h" * 40, target_oid="t" * 40,
        is_ancestor_of_head=True,
    )
    actions = _collect_actions(menu)
    reset_items = [a for a in actions
                   if "keep" in a.text.lower() or "discard" in a.text.lower()]
    assert reset_items
    assert all(a.enabled for a in reset_items)


def test_entries_not_shown_when_target_is_head(qtbot):
    state = RepoStateInfo(state=RepoState.CLEAN, head_branch="master")
    same = "s" * 40
    menu = _menu_with_new_section(
        qtbot, state=state, head_oid=same, target_oid=same,
        is_ancestor_of_head=False,
    )
    actions = _collect_actions(menu)
    texts = [a.text for a in actions]
    assert not any("Cherry-pick" in t for t in texts)
    assert not any("Revert commit" in t for t in texts)
```

- [ ] **Step 5: Run the graph context-menu tests**

Run: `uv run pytest tests/presentation/widgets/test_graph_context_menu.py -v`
Expected: all 6 new tests plus existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/widgets/graph.py tests/presentation/widgets/test_graph_context_menu.py
git commit -m "feat(graph): add cherry-pick/revert/reset context-menu entries"
```

---

## Task 13: Banner extension in working_tree.py

**Files:**
- Modify: `git_gui/presentation/widgets/working_tree.py`
- Modify: `tests/presentation/widgets/test_working_tree_banner.py`

- [ ] **Step 1: Add 4 new signals to `WorkingTreeWidget`**

Find the block starting at line 88 in `working_tree.py` (the existing banner signals) and append:

```python
    cherry_pick_abort_requested = Signal()
    revert_abort_requested = Signal()
    cherry_pick_continue_requested = Signal()
    revert_continue_requested = Signal()
```

- [ ] **Step 2: Extend `update_conflict_banner`**

Find `update_conflict_banner` (line 358). After the existing `REBASING` branch, add:

```python
        elif state_name == "CHERRY_PICKING":
            self._banner_label.setText("\u26a0 Cherry-pick in progress")
            self._conflict_banner.setVisible(True)
            self._btn_commit.setText("Continue Cherry-pick")
        elif state_name == "REVERTING":
            self._banner_label.setText("\u26a0 Revert in progress")
            self._conflict_banner.setVisible(True)
            self._btn_commit.setText("Continue Revert")
```

- [ ] **Step 3: Extend `_on_abort_clicked` and `_on_commit`**

Find `_on_abort_clicked` (line 375). After the existing `elif state == "REBASING":` branch, add:

```python
        elif state == "CHERRY_PICKING":
            self.cherry_pick_abort_requested.emit()
        elif state == "REVERTING":
            self.revert_abort_requested.emit()
```

Find `_on_commit` (line 293). After the existing `elif state == "REBASING":` branch, add:

```python
        elif state == "CHERRY_PICKING":
            self.cherry_pick_continue_requested.emit()
        elif state == "REVERTING":
            self.revert_continue_requested.emit()
```

Note: `_on_commit` currently emits signals with a `msg` argument; the cherry-pick / revert continuations don't need a message (we use `GIT_EDITOR=true` in `CommitOpsCli`). The new signals are 0-arg, which matches the existing `merge_abort_requested` / `rebase_abort_requested` pattern.

- [ ] **Step 4: Extend the banner tests**

Open `tests/presentation/widgets/test_working_tree_banner.py`. At the end of the file, append:

```python
def test_banner_visible_during_cherry_pick(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("CHERRY_PICKING")
    assert w._conflict_banner.isVisible() is True
    assert "Cherry-pick" in w._banner_label.text()
    assert "Continue Cherry-pick" in w._btn_commit.text()


def test_banner_visible_during_revert(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("REVERTING")
    assert w._conflict_banner.isVisible() is True
    assert "Revert" in w._banner_label.text()
    assert "Continue Revert" in w._btn_commit.text()


def test_abort_emits_cherry_pick_abort(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("CHERRY_PICKING")
    received = []
    w.cherry_pick_abort_requested.connect(lambda: received.append("cp_abort"))
    w._btn_abort.click()
    assert received == ["cp_abort"]


def test_abort_emits_revert_abort(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("REVERTING")
    received = []
    w.revert_abort_requested.connect(lambda: received.append("rv_abort"))
    w._btn_abort.click()
    assert received == ["rv_abort"]


def test_commit_emits_cherry_pick_continue(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("CHERRY_PICKING")
    received = []
    w.cherry_pick_continue_requested.connect(lambda: received.append("cp_cont"))
    w._on_commit()
    assert received == ["cp_cont"]


def test_commit_emits_revert_continue(qtbot):
    w = _make_widget(qtbot)
    w.update_conflict_banner("REVERTING")
    received = []
    w.revert_continue_requested.connect(lambda: received.append("rv_cont"))
    w._on_commit()
    assert received == ["rv_cont"]
```

- [ ] **Step 5: Run banner tests**

Run: `uv run pytest tests/presentation/widgets/test_working_tree_banner.py -v`
Expected: all new + existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/widgets/working_tree.py tests/presentation/widgets/test_working_tree_banner.py
git commit -m "feat(working-tree): extend conflict banner for cherry-pick / revert"
```

---

## Task 14: Banner extension in diff.py

**Files:**
- Modify: `git_gui/presentation/widgets/diff.py`

- [ ] **Step 1: Add 4 new signals to the diff widget**

Find the existing `merge_abort_requested = Signal()` line (around `diff.py:74`). After the last banner signal, add:

```python
    cherry_pick_abort_requested = Signal()
    revert_abort_requested = Signal()
    cherry_pick_continue_requested = Signal()
    revert_continue_requested = Signal()
```

- [ ] **Step 2: Extend `update_state_banner`**

Find `update_state_banner` at `diff.py:177`. After the existing `REBASING` branch, add:

```python
        elif state_name == "CHERRY_PICKING":
            self._banner_label.setText("\u26a0 Cherry-pick in progress")
            self._state_banner.setVisible(True)
        elif state_name == "REVERTING":
            self._banner_label.setText("\u26a0 Revert in progress")
            self._state_banner.setVisible(True)
```

(Keep the existing visibility-setting logic consistent with how MERGING/REBASING are handled.)

- [ ] **Step 3: Extend `_on_banner_abort` and `_on_banner_continue`**

Find `_on_banner_abort` (line 191). Add new branches:

```python
        elif state == "CHERRY_PICKING":
            self.cherry_pick_abort_requested.emit()
        elif state == "REVERTING":
            self.revert_abort_requested.emit()
```

Find `_on_banner_continue` (line 198). Add:

```python
        elif state == "CHERRY_PICKING":
            self.cherry_pick_continue_requested.emit()
        elif state == "REVERTING":
            self.revert_continue_requested.emit()
```

- [ ] **Step 4: Run any existing diff widget tests**

Run: `uv run pytest tests/presentation/widgets/test_diff_widget.py -v`
Expected: all tests pass (no existing tests target these states, so this is a sanity run).

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/widgets/diff.py
git commit -m "feat(diff): extend state banner for cherry-pick / revert"
```

---

## Task 15: MainWindow wiring — connect signals and implement handlers

**Files:**
- Modify: `git_gui/presentation/main_window.py`

- [ ] **Step 1: Import `ResetDialog` and `ResetMode`**

Near the top of `main_window.py`, find the existing dialog imports (`from git_gui.presentation.dialogs...`). Add:

```python
from git_gui.presentation.dialogs.reset_dialog import ResetDialog
from git_gui.domain.entities import ResetMode
```

(Merge with any existing entities import line.)

- [ ] **Step 2: Connect 3 new graph signals**

In the graph signal-wiring block (around `main_window.py:163`, where `merge_branch_requested` is connected), append:

```python
        self._graph.cherry_pick_requested.connect(self._on_cherry_pick)
        self._graph.revert_commit_requested.connect(self._on_revert)
        self._graph.reset_to_commit_requested.connect(self._on_reset_to_commit)
```

- [ ] **Step 3: Connect 4 new banner signals on working_tree and diff**

In the working_tree signal-wiring block (around `main_window.py:120`), append:

```python
        self._working_tree.cherry_pick_abort_requested.connect(self._on_cherry_pick_abort)
        self._working_tree.revert_abort_requested.connect(self._on_revert_abort)
        self._working_tree.cherry_pick_continue_requested.connect(self._on_cherry_pick_continue)
        self._working_tree.revert_continue_requested.connect(self._on_revert_continue)
```

In the diff signal-wiring block (around `main_window.py:133`), append:

```python
        self._diff.cherry_pick_abort_requested.connect(self._on_cherry_pick_abort)
        self._diff.revert_abort_requested.connect(self._on_revert_abort)
        self._diff.cherry_pick_continue_requested.connect(self._on_cherry_pick_continue)
        self._diff.revert_continue_requested.connect(self._on_revert_continue)
```

- [ ] **Step 4: Add 7 handler methods**

Append these methods to `MainWindow`, after `_on_rebase_continue` (around line 401):

```python
    def _on_cherry_pick(self, oid: str) -> None:
        short = oid[:7]
        try:
            self._commands.cherry_pick.execute(oid)
            self._log_panel.log(f"Cherry-pick: {short}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Cherry-pick {short} — ERROR: {e}")
        self._reload()

    def _on_revert(self, oid: str) -> None:
        short = oid[:7]
        try:
            self._commands.revert_commit.execute(oid)
            self._log_panel.log(f"Revert: {short}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Revert {short} — ERROR: {e}")
        self._reload()

    def _on_reset_to_commit(self, oid: str, default_mode) -> None:
        short = oid[:7]
        try:
            commit = self._queries.get_commit_detail.execute(oid)
            head_branch = self._queries.get_repo_state.execute().head_branch or "HEAD"
            dirty_files = self._queries.get_working_tree.execute()

            dlg = ResetDialog(
                branch_name=head_branch,
                short_sha=short,
                commit_subject=(commit.message.splitlines()[0] if commit.message else ""),
                default_mode=default_mode,
                dirty_files=dirty_files,
                parent=self,
            )
            if dlg.exec() != ResetDialog.Accepted:
                return
            mode = dlg.result_mode()
            self._commands.reset_branch.execute(oid, mode)
            self._log_panel.log(f"Reset {head_branch} --{mode.value.lower()} to {short}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Reset to {short} — ERROR: {e}")
        self._reload()

    def _on_cherry_pick_abort(self) -> None:
        try:
            self._commands.cherry_pick_abort.execute()
            self._log_panel.log("Cherry-pick aborted")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Cherry-pick abort — ERROR: {e}")
        self._reload()

    def _on_cherry_pick_continue(self) -> None:
        try:
            if self._queries.has_unresolved_conflicts.execute():
                self._log_panel.expand()
                self._log_panel.log_error("Resolve all conflicts and stage files first")
                return
            self._commands.cherry_pick_continue.execute()
            self._log_panel.log("Cherry-pick continued")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Cherry-pick continue — ERROR: {e}")
        self._reload()

    def _on_revert_abort(self) -> None:
        try:
            self._commands.revert_abort.execute()
            self._log_panel.log("Revert aborted")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Revert abort — ERROR: {e}")
        self._reload()

    def _on_revert_continue(self) -> None:
        try:
            if self._queries.has_unresolved_conflicts.execute():
                self._log_panel.expand()
                self._log_panel.log_error("Resolve all conflicts and stage files first")
                return
            self._commands.revert_continue.execute()
            self._log_panel.log("Revert continued")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Revert continue — ERROR: {e}")
        self._reload()
```

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Smoke-test the UI manually**

Run: `uv run python main.py`
Open a test repository and verify:
1. Right-clicking a commit shows "Cherry-pick commit …", "Revert commit …", and a "Reset … to …" submenu.
2. Cherry-picking a clean commit succeeds (graph reloads with new HEAD).
3. Reverting a commit succeeds.
4. Reset → Hard opens the dialog with a dirty-file list (create some local changes first).
5. Reset → Soft opens the dialog without a dirty-file list.
6. Causing a cherry-pick conflict (e.g., cherry-pick from a divergent branch) shows the conflict banner with "Cherry-pick in progress" and a "Continue Cherry-pick" button.
7. Abort button clears the CHERRY_PICK_HEAD state.

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/main_window.py
git commit -m "feat(main_window): wire cherry-pick / revert / reset flows"
```

---

## Task 16: Final full-suite run and README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Full test run**

Run: `uv run pytest tests/ -v`
Expected: no failures, no new warnings.

- [ ] **Step 2: Update README features list**

In `README.md`, under the existing "Branch Management" section or as a new "Commit Operations" section, add:

```markdown
### Commit Operations
- **Cherry-pick** — right-click a commit in the graph → "Cherry-pick commit …"
- **Revert** — right-click a commit → "Revert commit …" (creates an inverse commit on HEAD)
- **Reset** — right-click an ancestor of HEAD → "Reset <branch> to <sha> ▸" with soft / mixed / hard modes; hard shows a dirty-file preview before confirming
- Cherry-pick / revert conflicts are surfaced by the existing conflict banner with Abort and Continue buttons
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document cherry-pick / revert / reset in README"
```

---

## Self-Review Checklist

After completing the implementation, verify against the spec:

1. **Cherry-pick** — graph context menu entry, one-shot execution, merge-commit `-m 1` handled.
2. **Revert** — graph context menu entry, one-shot, merge-commit `-m 1` handled.
3. **Reset** — submenu with 3 modes, always opens `ResetDialog`, dirty-file list for HARD only, ancestor-only enablement.
4. **Conflicts** — banner recognizes CHERRY_PICKING / REVERTING; Abort and Continue buttons work in both working-tree and diff widgets.
5. **Clean Architecture** — domain defines `ResetMode` + 7 ports; application has 7 thin use cases; infrastructure has `CommitOpsCli` + 7 writer methods on `Pygit2Repository`; presentation has `ResetDialog`, graph menu entries, banner extensions, and main_window wiring.
6. **Tests** — CLI adapter (11), reset (4), application (8), dialog (8), context menu (6), banner (6) — all with real git repos where applicable, no mocks for Git behavior.
