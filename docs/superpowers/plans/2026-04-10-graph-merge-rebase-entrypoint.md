# Commit Graph Merge/Rebase Entry Point — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add merge/rebase actions to the commit graph context menu, targeting either branches on a commit or the commit itself, with disabled-state tooltips for invalid situations (detached HEAD, in-progress merge/rebase, ancestor merges).

**Architecture:** Add a `repo_state()` query and `is_ancestor()` reader method to detect when actions should be disabled. Add `merge_commit(oid)` / `rebase_onto_commit(oid)` writer methods that share core logic with the existing branch-based versions. Extend `graph.py`'s `_show_context_menu` with a new "Merge / Rebase" section, wired into existing main_window error-logging handlers.

**Tech Stack:** Python, PySide6 (Qt), pygit2, pytest, pytest-qt, uv.

**Spec:** `docs/superpowers/specs/2026-04-10-graph-merge-rebase-entrypoint-design.md`

---

## File Structure

**Modified:**
- `git_gui/domain/entities.py` — add `RepoState` enum + `RepoStateInfo` dataclass
- `git_gui/domain/ports.py` — extend `IRepositoryReader` and `IRepositoryWriter` protocols
- `git_gui/infrastructure/pygit2_repo.py` — implement new reader/writer methods
- `git_gui/application/queries.py` — add `GetRepoState`
- `git_gui/application/commands.py` — add `MergeCommit`, `RebaseOntoCommit`
- `git_gui/presentation/bus.py` — wire new query and commands
- `git_gui/presentation/widgets/graph.py` — new signals, context menu logic
- `git_gui/presentation/main_window.py` — wire new signals to handlers

**Test files modified/added:**
- `tests/infrastructure/test_writes.py` — add tests for `merge_commit`, `rebase_onto_commit`
- `tests/infrastructure/test_reads.py` — add tests for `repo_state`, `is_ancestor`
- `tests/application/test_commands.py` — add tests for `MergeCommit`, `RebaseOntoCommit`
- `tests/application/test_queries.py` — add test for `GetRepoState`
- `tests/presentation/widgets/test_graph_context_menu.py` (new) — context menu rules

---

## Task 1: Add `RepoState` enum and `RepoStateInfo` dataclass

**Files:**
- Modify: `git_gui/domain/entities.py`

- [ ] **Step 1: Add the enum and dataclass to entities.py**

Append at the bottom of `git_gui/domain/entities.py`:

```python
from enum import Enum


class RepoState(str, Enum):
    CLEAN = "CLEAN"
    MERGING = "MERGING"
    REBASING = "REBASING"
    CHERRY_PICKING = "CHERRY_PICKING"
    REVERTING = "REVERTING"
    DETACHED_HEAD = "DETACHED_HEAD"


@dataclass(frozen=True)
class RepoStateInfo:
    state: RepoState
    head_branch: str | None
```

(If `from enum import Enum` or `from dataclasses import dataclass` are already imported, do not duplicate.)

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from git_gui.domain.entities import RepoState, RepoStateInfo; print(RepoState.CLEAN, RepoStateInfo(RepoState.CLEAN, 'main'))"`
Expected: `RepoState.CLEAN RepoStateInfo(state=<RepoState.CLEAN: 'CLEAN'>, head_branch='main')`

- [ ] **Step 3: Commit**

```bash
git add git_gui/domain/entities.py
git commit -m "feat(domain): add RepoState enum and RepoStateInfo dataclass"
```

---

## Task 2: Extend reader/writer protocols

**Files:**
- Modify: `git_gui/domain/ports.py`

- [ ] **Step 1: Add reader methods to `IRepositoryReader`**

In `git_gui/domain/ports.py`, add to the imports:

```python
from git_gui.domain.entities import Branch, Commit, CommitStat, FileStatus, Hunk, LocalBranchInfo, Remote, RepoStateInfo, Stash, Submodule, Tag
```

Add at the bottom of the `IRepositoryReader` Protocol body (after the existing methods):

```python
    def repo_state(self) -> RepoStateInfo: ...
    def is_ancestor(self, ancestor_oid: str, descendant_oid: str) -> bool: ...
```

- [ ] **Step 2: Add writer methods to `IRepositoryWriter`**

Add after the existing `merge` / `rebase` lines in the `IRepositoryWriter` Protocol body:

```python
    def merge_commit(self, oid: str) -> None: ...
    def rebase_onto_commit(self, oid: str) -> None: ...
```

- [ ] **Step 3: Verify imports load**

Run: `uv run python -c "from git_gui.domain.ports import IRepositoryReader, IRepositoryWriter; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add git_gui/domain/ports.py
git commit -m "feat(domain): add repo_state/is_ancestor/merge_commit/rebase_onto_commit ports"
```

---

## Task 3: Implement `repo_state()` in pygit2_repo (TDD)

**Files:**
- Test: `tests/infrastructure/test_reads.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Write failing tests**

Look at the top of `tests/infrastructure/test_reads.py` for the existing test fixture pattern (it likely uses a `tmp_path` fixture creating a real git repo). Add these tests at the bottom:

```python
def test_repo_state_clean(tmp_repo):
    # tmp_repo: PyGit2RepositoryReader on a fresh repo with one commit on main
    info = tmp_repo.reader.repo_state()
    assert info.state.name == "CLEAN"
    assert info.head_branch == "main" or info.head_branch == "master"


def test_repo_state_detached(tmp_repo):
    head_oid = tmp_repo.reader.get_head_oid()
    tmp_repo.writer.checkout_commit(head_oid)
    info = tmp_repo.reader.repo_state()
    assert info.state.name == "DETACHED_HEAD"
    assert info.head_branch is None


def test_repo_state_merging(tmp_repo):
    # Create a divergent branch and start a merge that conflicts
    import pygit2
    head_oid = tmp_repo.reader.get_head_oid()
    tmp_repo.writer.create_branch("feature", head_oid)
    # Make a commit on main
    (tmp_repo.workdir / "a.txt").write_text("main change")
    tmp_repo.writer.stage(["a.txt"])
    tmp_repo.writer.commit("main change")
    # Make a conflicting commit on feature
    tmp_repo.writer.checkout("feature")
    (tmp_repo.workdir / "a.txt").write_text("feature change")
    tmp_repo.writer.stage(["a.txt"])
    tmp_repo.writer.commit("feature change")
    tmp_repo.writer.checkout("main" if "main" in [b.name for b in tmp_repo.reader.get_branches()] else "master")
    try:
        tmp_repo.writer.merge("feature")
    except Exception:
        pass
    # Force into MERGING state via raw pygit2 if merge() didn't leave it there
    repo = tmp_repo._repo  # internal access for test
    repo.merge(repo.branches.local["feature"].target)
    info = tmp_repo.reader.repo_state()
    assert info.state.name == "MERGING"
```

(If `tmp_repo` fixture doesn't exist with that exact shape, adapt to whatever fixture this test file already uses to create a `PyGit2RepositoryReader` + writer pair on a temp repo. Look at existing tests in this file for the pattern before writing — copy it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_reads.py -v -k repo_state`
Expected: FAIL with `AttributeError` (no `repo_state` method) or import error.

- [ ] **Step 3: Implement `repo_state()` in pygit2_repo.py**

In `git_gui/infrastructure/pygit2_repo.py`, add to the imports at the top if not present:

```python
from git_gui.domain.entities import (..., RepoState, RepoStateInfo)
```

(Merge into the existing entities import line.)

Add this method on the `PyGit2RepositoryReader` class (place near `get_head_oid`):

```python
def repo_state(self) -> RepoStateInfo:
    import pygit2
    # Detached HEAD takes priority over the cleanup-state check, because a
    # detached HEAD with no in-progress operation is still "abnormal" for
    # merge/rebase purposes.
    if self._repo.head_is_detached:
        return RepoStateInfo(state=RepoState.DETACHED_HEAD, head_branch=None)

    state = self._repo.state()
    state_map = {
        pygit2.GIT_REPOSITORY_STATE_NONE: RepoState.CLEAN,
        pygit2.GIT_REPOSITORY_STATE_MERGE: RepoState.MERGING,
        pygit2.GIT_REPOSITORY_STATE_REVERT: RepoState.REVERTING,
        pygit2.GIT_REPOSITORY_STATE_CHERRYPICK: RepoState.CHERRY_PICKING,
        pygit2.GIT_REPOSITORY_STATE_REBASE: RepoState.REBASING,
        pygit2.GIT_REPOSITORY_STATE_REBASE_INTERACTIVE: RepoState.REBASING,
        pygit2.GIT_REPOSITORY_STATE_REBASE_MERGE: RepoState.REBASING,
        pygit2.GIT_REPOSITORY_STATE_APPLY_MAILBOX: RepoState.CLEAN,
        pygit2.GIT_REPOSITORY_STATE_APPLY_MAILBOX_OR_REBASE: RepoState.REBASING,
    }
    mapped = state_map.get(state, RepoState.CLEAN)
    return RepoStateInfo(state=mapped, head_branch=self._repo.head.shorthand)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_reads.py -v -k repo_state`
Expected: PASS for all three.

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_reads.py
git commit -m "feat(infra): implement repo_state() with detached/merging/rebasing detection"
```

---

## Task 4: Implement `is_ancestor()` in pygit2_repo (TDD)

**Files:**
- Test: `tests/infrastructure/test_reads.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Write failing test**

Append to `tests/infrastructure/test_reads.py`:

```python
def test_is_ancestor(tmp_repo):
    first_oid = tmp_repo.reader.get_head_oid()
    (tmp_repo.workdir / "b.txt").write_text("b")
    tmp_repo.writer.stage(["b.txt"])
    second = tmp_repo.writer.commit("second")
    second_oid = second.oid

    assert tmp_repo.reader.is_ancestor(first_oid, second_oid) is True
    assert tmp_repo.reader.is_ancestor(second_oid, first_oid) is False
    assert tmp_repo.reader.is_ancestor(first_oid, first_oid) is False
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/infrastructure/test_reads.py::test_is_ancestor -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement**

Add to `PyGit2RepositoryReader` in `pygit2_repo.py`:

```python
def is_ancestor(self, ancestor_oid: str, descendant_oid: str) -> bool:
    if ancestor_oid == descendant_oid:
        return False
    return bool(self._repo.descendant_of(descendant_oid, ancestor_oid))
```

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/infrastructure/test_reads.py::test_is_ancestor -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_reads.py
git commit -m "feat(infra): implement is_ancestor()"
```

---

## Task 5: Refactor existing `merge` to extract a commit-id core

**Files:**
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Replace `merge()` with two methods sharing a helper**

Replace the existing `merge` method (around line 556) with:

```python
def merge(self, branch: str) -> None:
    if branch in self._repo.branches.local:
        ref = self._repo.branches.local[branch]
    else:
        ref = self._repo.branches.remote[branch]
    self._merge_oid(ref.target, label=f"branch '{branch}'")

def merge_commit(self, oid: str) -> None:
    target = pygit2.Oid(hex=oid)
    self._merge_oid(target, label=f"commit {oid[:7]}")

def _merge_oid(self, target_oid, label: str) -> None:
    merge_result, _ = self._repo.merge_analysis(target_oid)
    if merge_result & pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD:
        self._repo.checkout_tree(self._repo.get(target_oid))
        self._repo.head.set_target(target_oid)
    elif merge_result & pygit2.GIT_MERGE_ANALYSIS_NORMAL:
        self._repo.merge(target_oid)
        if not self._repo.index.conflicts:
            self._repo.index.write()
            tree = self._repo.index.write_tree()
            sig = self._get_signature()
            self._repo.create_commit(
                "HEAD", sig, sig,
                f"Merge {label}",
                tree,
                [self._repo.head.target, target_oid],
            )
            self._repo.state_cleanup()
```

- [ ] **Step 2: Run existing merge tests to ensure no regression**

Run: `uv run pytest tests/ -v -k merge`
Expected: All previously-passing merge tests still pass.

- [ ] **Step 3: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py
git commit -m "refactor(infra): extract _merge_oid helper, add merge_commit"
```

---

## Task 6: Add `merge_commit` integration test

**Files:**
- Test: `tests/infrastructure/test_writes.py`

- [ ] **Step 1: Write test**

Look at `tests/infrastructure/test_writes.py` for the existing fixture pattern, then add:

```python
def test_merge_commit_fast_forward(tmp_repo):
    # Create commit on a branch ahead of HEAD, then merge by oid
    head_oid = tmp_repo.reader.get_head_oid()
    tmp_repo.writer.create_branch("feature", head_oid)
    tmp_repo.writer.checkout("feature")
    (tmp_repo.workdir / "f.txt").write_text("f")
    tmp_repo.writer.stage(["f.txt"])
    new_commit = tmp_repo.writer.commit("on feature")
    tmp_repo.writer.checkout("main" if "main" in [b.name for b in tmp_repo.reader.get_branches() if not b.is_remote] else "master")

    tmp_repo.writer.merge_commit(new_commit.oid)

    assert tmp_repo.reader.get_head_oid() == new_commit.oid
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/infrastructure/test_writes.py::test_merge_commit_fast_forward -v`
Expected: PASS (because Task 5 already added the implementation).

- [ ] **Step 3: Commit**

```bash
git add tests/infrastructure/test_writes.py
git commit -m "test(infra): cover merge_commit fast-forward"
```

---

## Task 7: Implement `rebase_onto_commit` (TDD)

**Files:**
- Test: `tests/infrastructure/test_writes.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Write failing test**

Append to `tests/infrastructure/test_writes.py`:

```python
def test_rebase_onto_commit(tmp_repo):
    # main: A -> B; feature branches off A and adds C; rebase main onto C
    head_oid = tmp_repo.reader.get_head_oid()  # A
    tmp_repo.writer.create_branch("feature", head_oid)
    # main adds B
    (tmp_repo.workdir / "b.txt").write_text("b")
    tmp_repo.writer.stage(["b.txt"])
    b = tmp_repo.writer.commit("B on main")
    # feature adds C
    tmp_repo.writer.checkout("feature")
    (tmp_repo.workdir / "c.txt").write_text("c")
    tmp_repo.writer.stage(["c.txt"])
    c = tmp_repo.writer.commit("C on feature")
    # back to main, rebase onto commit C
    main_name = "main" if "main" in [br.name for br in tmp_repo.reader.get_branches() if not br.is_remote] else "master"
    tmp_repo.writer.checkout(main_name)

    tmp_repo.writer.rebase_onto_commit(c.oid)

    new_head = tmp_repo.reader.get_head_oid()
    assert tmp_repo.reader.is_ancestor(c.oid, new_head) is True
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/infrastructure/test_writes.py::test_rebase_onto_commit -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement**

In `pygit2_repo.py`, refactor `rebase` and add `rebase_onto_commit`:

```python
def rebase(self, branch: str) -> None:
    onto_ref = self._repo.branches.local[branch]
    self._rebase_onto(onto_ref.target)

def rebase_onto_commit(self, oid: str) -> None:
    self._rebase_onto(pygit2.Oid(hex=oid))

def _rebase_onto(self, target_oid) -> None:
    rebase = self._repo.rebase(onto=target_oid)
    while True:
        op = rebase.next()
        if op is None:
            break
    rebase.finish(self._get_signature())
```

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/infrastructure/test_writes.py::test_rebase_onto_commit -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_writes.py
git commit -m "feat(infra): implement rebase_onto_commit"
```

---

## Task 8: Add `GetRepoState` query (TDD)

**Files:**
- Test: `tests/application/test_queries.py`
- Modify: `git_gui/application/queries.py`

- [ ] **Step 1: Write failing test**

Append to `tests/application/test_queries.py`:

```python
from git_gui.application.queries import GetRepoState
from git_gui.domain.entities import RepoState, RepoStateInfo


class _FakeReader:
    def __init__(self, info):
        self._info = info
    def repo_state(self):
        return self._info


def test_get_repo_state_passthrough():
    info = RepoStateInfo(state=RepoState.MERGING, head_branch="main")
    q = GetRepoState(_FakeReader(info))
    assert q.execute() == info
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/application/test_queries.py::test_get_repo_state_passthrough -v`
Expected: FAIL — `ImportError: cannot import name 'GetRepoState'`.

- [ ] **Step 3: Implement**

Append to `git_gui/application/queries.py`:

```python
from git_gui.domain.entities import RepoStateInfo


class GetRepoState:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> RepoStateInfo:
        return self._reader.repo_state()
```

(Merge the entities import into the existing entities import line at the top of the file rather than adding a duplicate.)

- [ ] **Step 4: Run**

Run: `uv run pytest tests/application/test_queries.py::test_get_repo_state_passthrough -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add git_gui/application/queries.py tests/application/test_queries.py
git commit -m "feat(application): add GetRepoState query"
```

---

## Task 9: Add `MergeCommit` and `RebaseOntoCommit` commands (TDD)

**Files:**
- Test: `tests/application/test_commands.py`
- Modify: `git_gui/application/commands.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/application/test_commands.py`:

```python
from git_gui.application.commands import MergeCommit, RebaseOntoCommit


class _FakeWriter:
    def __init__(self):
        self.merge_commit_called = None
        self.rebase_onto_commit_called = None
    def merge_commit(self, oid):
        self.merge_commit_called = oid
    def rebase_onto_commit(self, oid):
        self.rebase_onto_commit_called = oid


def test_merge_commit_passes_oid():
    w = _FakeWriter()
    MergeCommit(w).execute("abcdef1234")
    assert w.merge_commit_called == "abcdef1234"


def test_rebase_onto_commit_passes_oid():
    w = _FakeWriter()
    RebaseOntoCommit(w).execute("abcdef1234")
    assert w.rebase_onto_commit_called == "abcdef1234"
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/application/test_commands.py -v -k "merge_commit or rebase_onto_commit"`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

Append to `git_gui/application/commands.py` (after the existing `Rebase` class):

```python
class MergeCommit:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, oid: str) -> None:
        self._writer.merge_commit(oid)


class RebaseOntoCommit:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, oid: str) -> None:
        self._writer.rebase_onto_commit(oid)
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/application/test_commands.py -v -k "merge_commit or rebase_onto_commit"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add git_gui/application/commands.py tests/application/test_commands.py
git commit -m "feat(application): add MergeCommit and RebaseOntoCommit"
```

---

## Task 10: Wire new query and commands into bus

**Files:**
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Update imports**

In `git_gui/presentation/bus.py`, change the queries import to include `GetRepoState`:

```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes, GetTags, GetRemoteTags, GetCommitStats,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
    GetCommitDetail, IsDirty, GetHeadOid, GetRepoState,
    ListRemotes, ListSubmodules, ListLocalBranchesWithUpstream,
)
```

And the commands import to include the two new commands:

```python
from git_gui.application.commands import (
    StageFiles, UnstageFiles, CreateCommit,
    Checkout, CheckoutCommit, CheckoutRemoteBranch, CreateBranch, DeleteBranch,
    CreateTag, DeleteTag, PushTag, DeleteRemoteTag,
    Merge, Rebase, MergeCommit, RebaseOntoCommit, Push, Pull, Fetch,
    Stash, PopStash, ApplyStash, DropStash,
    StageHunk, UnstageHunk, FetchAllPrune,
    DiscardFile, DiscardHunk,
    AddRemote, RemoveRemote, RenameRemote, SetRemoteUrl,
    AddSubmodule, RemoveSubmodule, SetSubmoduleUrl,
    SetBranchUpstream, UnsetBranchUpstream, RenameBranch, ResetBranchToRef,
)
```

- [ ] **Step 2: Add `get_repo_state` to QueryBus dataclass and `from_reader`**

Add `get_repo_state: GetRepoState` to the dataclass field list and `get_repo_state=GetRepoState(reader),` to the `from_reader` constructor call.

- [ ] **Step 3: Add `merge_commit` and `rebase_onto_commit` to CommandBus**

Add `merge_commit: MergeCommit` and `rebase_onto_commit: RebaseOntoCommit` to the CommandBus dataclass field list (next to `merge` and `rebase`), and add `merge_commit=MergeCommit(writer),` and `rebase_onto_commit=RebaseOntoCommit(writer),` to `from_writer`.

- [ ] **Step 4: Verify import**

Run: `uv run python -c "from git_gui.presentation.bus import QueryBus, CommandBus; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Run full test suite to confirm no regressions**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/bus.py
git commit -m "feat(bus): wire GetRepoState, MergeCommit, RebaseOntoCommit"
```

---

## Task 11: Add new signals + context menu logic to graph widget

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py`

- [ ] **Step 1: Add signals**

In `GraphWidget` (around line 94-105), add four new signals after the existing `delete_branch_requested` line:

```python
    merge_branch_requested = Signal(str)             # branch name (merge into current)
    merge_commit_requested = Signal(str)             # oid (merge commit into current)
    rebase_onto_branch_requested = Signal(str)       # branch name (rebase current onto)
    rebase_onto_commit_requested = Signal(str)       # oid (rebase current onto commit)
```

- [ ] **Step 2: Replace `_show_context_menu` with the extended version**

Replace the existing `_show_context_menu` method (`graph.py:393-451`) with this version. Preserve everything that was already there and add the new section after the "Delete branch" block:

```python
def _show_context_menu(self, pos) -> None:
    index = self._view.indexAt(pos)
    if not index.isValid():
        return
    oid = self._model.data(self._model.index(index.row(), 0), Qt.UserRole)
    if not oid or oid == WORKING_TREE_OID:
        return

    info = self._model.data(self._model.index(index.row(), 1), Qt.UserRole + 1)
    branch_names = info.branch_names if info else []

    menu = QMenu(self)
    menu.setToolTipsVisible(True)
    menu.setStyleSheet(
        "QMenu { padding: 6px; }"
        "QMenu::item { padding: 6px 24px 6px 20px; }"
    )

    menu.addAction("Create Branch").triggered.connect(
        lambda: self.create_branch_requested.emit(oid))
    menu.addAction("Create Tag...").triggered.connect(
        lambda: self.create_tag_requested.emit(oid))
    menu.addAction("Checkout (detached HEAD)").triggered.connect(
        lambda: self.checkout_commit_requested.emit(oid))

    real_branches = [n for n in branch_names if n != "HEAD" and not n.startswith("tag:")]
    try:
        all_branches = self._queries.get_branches.execute()
        local_set = {b.name for b in all_branches if not b.is_remote}
    except Exception:
        local_set = set()
    local_branches = [n for n in real_branches if n in local_set]

    if real_branches:
        menu.addSeparator()
        if len(real_branches) == 1:
            name = real_branches[0]
            menu.addAction(f"Checkout branch: {name}").triggered.connect(
                lambda: self.checkout_branch_requested.emit(name))
        else:
            sub = menu.addMenu("Checkout branch")
            for name in real_branches:
                sub.addAction(name).triggered.connect(
                    lambda _checked=False, n=name: self.checkout_branch_requested.emit(n))

    if local_branches:
        if len(local_branches) == 1:
            name = local_branches[0]
            menu.addAction(f"Delete branch: {name}").triggered.connect(
                lambda: self.delete_branch_requested.emit(name))
        else:
            sub = menu.addMenu("Delete branch")
            for name in local_branches:
                sub.addAction(name).triggered.connect(
                    lambda _checked=False, n=name: self.delete_branch_requested.emit(n))

    self._add_merge_rebase_section(menu, oid, real_branches)

    menu.exec(self._view.viewport().mapToGlobal(pos))
```

- [ ] **Step 3: Add the helper `_add_merge_rebase_section`**

Add this method to `GraphWidget` (immediately after `_show_context_menu`):

```python
def _add_merge_rebase_section(self, menu: QMenu, oid: str, branches_on_commit: list[str]) -> None:
    """Append the Merge / Rebase section to a context menu, applying disable rules."""
    try:
        state_info = self._queries.get_repo_state.execute()
    except Exception:
        return

    head_branch = state_info.head_branch
    state_name = state_info.state.name

    # Determine global disable reason (applies to every action)
    global_disable_reason: str | None = None
    if state_name == "DETACHED_HEAD":
        global_disable_reason = "HEAD is detached — checkout a branch first"
    elif state_name != "CLEAN":
        global_disable_reason = f"Repository is in {state_name} — resolve or abort first"

    # Compute candidate actions
    branch_targets = [b for b in branches_on_commit if b != head_branch]

    try:
        head_oid = self._queries.get_head_oid.execute()
    except Exception:
        head_oid = None

    show_commit_merge = bool(head_oid) and oid != head_oid
    show_commit_rebase = bool(head_oid) and oid != head_oid

    is_ancestor_of_head = False
    if show_commit_merge and head_oid:
        try:
            is_ancestor_of_head = self._queries.is_ancestor.execute(oid, head_oid)
        except Exception:
            is_ancestor_of_head = False

    if show_commit_merge and is_ancestor_of_head:
        show_commit_merge = False

    # If nothing to show, bail before adding the separator
    if not branch_targets and not show_commit_merge and not show_commit_rebase:
        return

    menu.addSeparator()

    short_oid = oid[:7]
    head_label = head_branch or "HEAD"

    def _add(label: str, tooltip: str | None, signal_emit) -> None:
        action = menu.addAction(label)
        if global_disable_reason:
            action.setEnabled(False)
            action.setToolTip(global_disable_reason)
        elif tooltip:
            action.setEnabled(False)
            action.setToolTip(tooltip)
        else:
            action.triggered.connect(signal_emit)

    for b in branch_targets:
        ancestor_tooltip = None
        try:
            if head_oid and self._queries.is_ancestor.execute(oid, head_oid):
                ancestor_tooltip = "Already up to date"
        except Exception:
            pass
        _add(
            f"Merge {b} into {head_label}",
            ancestor_tooltip,
            lambda _checked=False, n=b: self.merge_branch_requested.emit(n),
        )

    for b in branch_targets:
        _add(
            f"Rebase {head_label} onto {b}",
            None,
            lambda _checked=False, n=b: self.rebase_onto_branch_requested.emit(n),
        )

    if show_commit_merge:
        _add(
            f"Merge commit {short_oid} into {head_label}",
            None,
            lambda _checked=False, o=oid: self.merge_commit_requested.emit(o),
        )

    if show_commit_rebase:
        _add(
            f"Rebase {head_label} onto commit {short_oid}",
            None,
            lambda _checked=False, o=oid: self.rebase_onto_commit_requested.emit(o),
        )
```

Note: this references `self._queries.is_ancestor` — that is added as a query in Task 12 (we expose it as a thin query so widget code only touches the bus).

- [ ] **Step 4: Verify the file still imports**

Run: `uv run python -c "from git_gui.presentation.widgets.graph import GraphWidget; print('ok')"`
Expected: `ok` (or an error if syntax is broken — fix before continuing).

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/widgets/graph.py
git commit -m "feat(graph): add merge/rebase context menu section with disable rules"
```

---

## Task 12: Expose `is_ancestor` as a query and wire into bus

**Files:**
- Modify: `git_gui/application/queries.py`
- Modify: `git_gui/presentation/bus.py`
- Test: `tests/application/test_queries.py`

- [ ] **Step 1: Write failing test**

Append to `tests/application/test_queries.py`:

```python
from git_gui.application.queries import IsAncestor


class _FakeAncestorReader:
    def is_ancestor(self, a, d):
        return (a, d) == ("anc", "desc")


def test_is_ancestor_query_passthrough():
    q = IsAncestor(_FakeAncestorReader())
    assert q.execute("anc", "desc") is True
    assert q.execute("x", "y") is False
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/application/test_queries.py::test_is_ancestor_query_passthrough -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement query**

Append to `git_gui/application/queries.py`:

```python
class IsAncestor:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, ancestor_oid: str, descendant_oid: str) -> bool:
        return self._reader.is_ancestor(ancestor_oid, descendant_oid)
```

- [ ] **Step 4: Wire into bus**

In `git_gui/presentation/bus.py`, add `IsAncestor` to the queries import. Add `is_ancestor: IsAncestor` to `QueryBus` dataclass and `is_ancestor=IsAncestor(reader),` to `from_reader`.

- [ ] **Step 5: Run query test**

Run: `uv run pytest tests/application/test_queries.py::test_is_ancestor_query_passthrough -v`
Expected: PASS

- [ ] **Step 6: Run full suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add git_gui/application/queries.py git_gui/presentation/bus.py tests/application/test_queries.py
git commit -m "feat(queries): expose IsAncestor query and wire into bus"
```

---

## Task 13: Wire main_window handlers for new signals

**Files:**
- Modify: `git_gui/presentation/main_window.py`

- [ ] **Step 1: Connect signals**

In `main_window.py`, in the "Graph context menu signals" block (around line 124-135), add:

```python
        self._graph.merge_branch_requested.connect(self._on_merge)
        self._graph.merge_commit_requested.connect(self._on_merge_commit)
        self._graph.rebase_onto_branch_requested.connect(self._on_rebase)
        self._graph.rebase_onto_commit_requested.connect(self._on_rebase_onto_commit)
```

(`_on_merge` and `_on_rebase` already exist for sidebar wiring; reuse them for the branch variants.)

- [ ] **Step 2: Add the two new handlers**

Add these methods after the existing `_on_rebase` method (around line 220):

```python
    def _on_merge_commit(self, oid: str) -> None:
        try:
            self._commands.merge_commit.execute(oid)
            self._log_panel.log(f"Merge: commit {oid[:7]} into current")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Merge commit {oid[:7]} — ERROR: {e}")
        self._reload()

    def _on_rebase_onto_commit(self, oid: str) -> None:
        try:
            self._commands.rebase_onto_commit.execute(oid)
            self._log_panel.log(f"Rebase onto commit {oid[:7]}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Rebase onto commit {oid[:7]} — ERROR: {e}")
        self._reload()
```

- [ ] **Step 3: Smoke-launch the app to verify wiring**

Run: `uv run python -c "from git_gui.presentation.main_window import MainWindow; print('import ok')"`
Expected: `import ok`

- [ ] **Step 4: Commit**

```bash
git add git_gui/presentation/main_window.py
git commit -m "feat(main_window): wire merge_commit and rebase_onto_commit handlers"
```

---

## Task 14: Widget tests for context menu rules

**Files:**
- Test: `tests/presentation/widgets/test_graph_context_menu.py` (new)

- [ ] **Step 1: Write the widget tests**

Create `tests/presentation/widgets/test_graph_context_menu.py` with this content. (If `tests/presentation/widgets/__init__.py` does not exist, create an empty one first.)

```python
"""Tests for the merge/rebase section of GraphWidget._show_context_menu.

We exercise _add_merge_rebase_section directly with a fake QueryBus to avoid
needing a fully-initialised GraphWidget.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
import pytest
from PySide6.QtWidgets import QMenu

from git_gui.domain.entities import RepoState, RepoStateInfo
from git_gui.presentation.widgets.graph import GraphWidget


@dataclass
class _FakeQuery:
    fn: Callable
    def execute(self, *args, **kwargs):
        return self.fn(*args, **kwargs)


class _FakeQueryBus:
    def __init__(self, *, state: RepoStateInfo, head_oid: str | None,
                 is_ancestor: Callable[[str, str], bool] = lambda a, d: False):
        self.get_repo_state = _FakeQuery(lambda: state)
        self.get_head_oid = _FakeQuery(lambda: head_oid)
        self.is_ancestor = _FakeQuery(is_ancestor)


class _Stub(GraphWidget.__mro__[0]):  # type: ignore[misc]
    pass


def _make_widget_with_queries(qtbot, queries) -> GraphWidget:
    # GraphWidget.__init__ does a lot — bypass it for these unit tests.
    w = GraphWidget.__new__(GraphWidget)
    w._queries = queries
    # GraphWidget inherits from QWidget; QObject signal infrastructure requires
    # the C++ part to exist. Initialise the QWidget base only.
    from PySide6.QtWidgets import QWidget
    QWidget.__init__(w)
    qtbot.addWidget(w)
    return w


def _labels(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if a.text()]


def _enabled(menu: QMenu, label: str) -> bool:
    for a in menu.actions():
        if a.text() == label:
            return a.isEnabled()
    raise AssertionError(f"action {label!r} not in menu")


def _tooltip(menu: QMenu, label: str) -> str:
    for a in menu.actions():
        if a.text() == label:
            return a.toolTip()
    raise AssertionError(f"action {label!r} not in menu")


def test_detached_head_disables_everything(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.DETACHED_HEAD, head_branch=None),
        head_oid="aaaaaaaaaaaa",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    menu.setToolTipsVisible(True)
    w._add_merge_rebase_section(menu, oid="bbbbbbbbbbbb", branches_on_commit=["feature"])

    assert _enabled(menu, "Merge feature into HEAD") is False
    assert "detached" in _tooltip(menu, "Merge feature into HEAD").lower()


def test_merging_state_disables_everything(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.MERGING, head_branch="main"),
        head_oid="aaaaaaaaaaaa",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    menu.setToolTipsVisible(True)
    w._add_merge_rebase_section(menu, oid="bbbbbbbbbbbb", branches_on_commit=["feature"])

    assert _enabled(menu, "Merge feature into main") is False
    assert "MERGING" in _tooltip(menu, "Merge feature into main")


def test_head_commit_with_no_other_branches_hides_section(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="aaaaaaaaaaaa",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    w._add_merge_rebase_section(menu, oid="aaaaaaaaaaaa", branches_on_commit=[])

    assert _labels(menu) == []  # nothing added


def test_ancestor_branch_merge_disabled_with_already_up_to_date(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="head1234567",
        is_ancestor=lambda a, d: a == "anc12345678" and d == "head1234567",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    menu.setToolTipsVisible(True)
    w._add_merge_rebase_section(menu, oid="anc12345678", branches_on_commit=["old-branch"])

    assert _enabled(menu, "Merge old-branch into main") is False
    assert _tooltip(menu, "Merge old-branch into main") == "Already up to date"
    # Rebase still allowed
    assert _enabled(menu, "Rebase main onto old-branch") is True


def test_normal_commit_emits_signals(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="head1234567",
    )
    w = _make_widget_with_queries(qtbot, queries)

    received_branch_merge: list[str] = []
    received_commit_merge: list[str] = []
    received_branch_rebase: list[str] = []
    received_commit_rebase: list[str] = []
    w.merge_branch_requested.connect(received_branch_merge.append)
    w.merge_commit_requested.connect(received_commit_merge.append)
    w.rebase_onto_branch_requested.connect(received_branch_rebase.append)
    w.rebase_onto_commit_requested.connect(received_commit_rebase.append)

    menu = QMenu()
    w._add_merge_rebase_section(menu, oid="newcommit12", branches_on_commit=["feature"])

    # Trigger each action
    for a in menu.actions():
        if a.text() == "Merge feature into main":
            a.trigger()
        elif a.text() == "Merge commit newcomm into main":
            a.trigger()
        elif a.text() == "Rebase main onto feature":
            a.trigger()
        elif a.text() == "Rebase main onto commit newcomm":
            a.trigger()

    assert received_branch_merge == ["feature"]
    assert received_commit_merge == ["newcommit12"]
    assert received_branch_rebase == ["feature"]
    assert received_commit_rebase == ["newcommit12"]


def test_multiple_branches_produce_one_action_each(qtbot):
    queries = _FakeQueryBus(
        state=RepoStateInfo(state=RepoState.CLEAN, head_branch="main"),
        head_oid="head1234567",
    )
    w = _make_widget_with_queries(qtbot, queries)
    menu = QMenu()
    w._add_merge_rebase_section(menu, oid="other123456", branches_on_commit=["a", "b"])

    labels = _labels(menu)
    assert "Merge a into main" in labels
    assert "Merge b into main" in labels
    assert "Rebase main onto a" in labels
    assert "Rebase main onto b" in labels
```

- [ ] **Step 2: Run the new tests**

Run: `uv run pytest tests/presentation/widgets/test_graph_context_menu.py -v`
Expected: All six tests pass. If a test fails because of label-format mismatches with the implementation in Task 11 (e.g., short-oid is `newcomm` vs `newcomm`), update the assertion to match the actual label format used in `_add_merge_rebase_section` (`oid[:7]`).

- [ ] **Step 3: Run full suite to confirm nothing else broke**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tests/presentation/widgets/test_graph_context_menu.py tests/presentation/widgets/__init__.py
git commit -m "test(graph): cover merge/rebase context menu rules"
```

---

## Task 15: Manual acceptance pass

- [ ] **Step 1: Launch the app on a real repo**

Run: `uv run python main.py` (or whatever the project's entry point is — confirm in `README.md` if unsure).

- [ ] **Step 2: Verify each scenario from the spec**

Walk through these scenarios manually and confirm behavior:

1. Right-click a commit on a feature branch (HEAD on main): see `Merge feature into main` and `Rebase main onto feature` enabled, plus `Merge commit <oid> into main` and `Rebase main onto commit <oid>`.
2. Right-click HEAD itself with no other branches: no merge/rebase section appears.
3. Right-click an ancestor commit of HEAD that carries a branch: `Merge <branch> into main` is greyed out with tooltip "Already up to date"; rebase still enabled.
4. Detach HEAD via "Checkout (detached HEAD)" then right-click: every merge/rebase action is greyed out with the detached tooltip.
5. Manually create a merge conflict (merge a divergent branch); right-click any commit: every merge/rebase action greyed out with the MERGING tooltip.

- [ ] **Step 3: If everything passes, commit any incidental fixes**

If you had to tweak labels or fix small issues during manual testing, commit them with a message like `fix(graph): adjust <thing> from manual test`.

---

## Out of Scope (deferred to later specs)

- Merge options UI (ff-only / no-ff / squash / commit message editing) — Spec B
- Conflict resolution UI, `--continue` / `--abort` — Spec C
- Toolbar or menu bar entry points — not planned
