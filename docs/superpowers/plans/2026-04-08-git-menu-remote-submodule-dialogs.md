# Git Menu: Remote & Submodule Dialogs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `Git` menubar menu with `Remotes...` and `Submodules...` dialogs for CRUD management of remotes and submodules, plus a one-way "Open" action that switches the main window to a submodule repo.

**Architecture:** Follows the existing clean-architecture stack: domain entities → port methods → application command/query classes → presentation buses → dialogs. Submodule mutations shell out to the `git` CLI via `subprocess` (pygit2 lacks reliable submodule add/remove). Remote operations use pygit2 directly. Mirrors the existing `View → Appearance...` / `ThemeDialog` / `install_appearance_menu` pattern.

**Tech Stack:** Python 3, PySide6, pygit2, pytest, pytest-qt, `uv run` for all execution.

**Spec:** `docs/superpowers/specs/2026-04-08-git-menu-remote-submodule-dialogs-design.md`

---

## File Structure

**Created:**
- `git_gui/presentation/menus/git_menu.py` — installs the Git menu and wires the two dialogs.
- `git_gui/presentation/dialogs/remote_dialog.py` — `RemoteDialog(QDialog)`.
- `git_gui/presentation/dialogs/submodule_dialog.py` — `SubmoduleDialog(QDialog)` with `submoduleOpenRequested(str)` signal.
- `git_gui/infrastructure/submodule_cli.py` — thin subprocess wrapper for `git submodule` commands; raises `SubmoduleCommandError`.
- `tests/presentation/dialogs/test_remote_dialog.py`
- `tests/presentation/dialogs/test_submodule_dialog.py`
- `tests/presentation/menus/test_git_menu.py`
- `tests/infrastructure/test_pygit2_repo_remotes.py`
- `tests/infrastructure/test_pygit2_repo_submodules.py`

**Modified:**
- `git_gui/domain/entities.py` — add `Remote` and `Submodule` dataclasses.
- `git_gui/domain/ports.py` — extend `IRepositoryReader` with `list_remotes`/`list_submodules`; extend `IRepositoryWriter` with remote and submodule mutation methods.
- `git_gui/application/queries.py` — add `ListRemotes` and `ListSubmodules` query classes.
- `git_gui/application/commands.py` — add `AddRemote`, `RemoveRemote`, `RenameRemote`, `SetRemoteUrl`, `AddSubmodule`, `RemoveSubmodule`, `SetSubmoduleUrl` command classes.
- `git_gui/presentation/bus.py` — register the new queries/commands on `QueryBus`/`CommandBus`.
- `git_gui/infrastructure/pygit2_repo.py` — implement remote CRUD (pygit2) and submodule CRUD (delegate to `submodule_cli`).
- `git_gui/presentation/main_window.py` — call `install_git_menu(self)` in `__init__`; add a slot that handles `submoduleOpenRequested` by calling `self._switch_repo(abs_path)`.

---

## Task 1: Domain entities for Remote and Submodule

**Files:**
- Modify: `git_gui/domain/entities.py`
- Test: `tests/domain/test_entities_remote_submodule.py`

- [ ] **Step 1: Write the failing test**

Create `tests/domain/test_entities_remote_submodule.py`:

```python
from git_gui.domain.entities import Remote, Submodule


def test_remote_dataclass_fields():
    r = Remote(name="origin", fetch_url="git@x:a.git", push_url="git@x:a.git")
    assert r.name == "origin"
    assert r.fetch_url == "git@x:a.git"
    assert r.push_url == "git@x:a.git"


def test_submodule_dataclass_fields():
    s = Submodule(path="libs/foo", url="git@x:foo.git", head_sha="abc123")
    assert s.path == "libs/foo"
    assert s.url == "git@x:foo.git"
    assert s.head_sha == "abc123"


def test_submodule_head_sha_optional():
    s = Submodule(path="libs/foo", url="git@x:foo.git", head_sha=None)
    assert s.head_sha is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_entities_remote_submodule.py -v`
Expected: FAIL with `ImportError: cannot import name 'Remote'`.

- [ ] **Step 3: Add the dataclasses**

Append to `git_gui/domain/entities.py`:

```python
@dataclass
class Remote:
    name: str
    fetch_url: str
    push_url: str


@dataclass
class Submodule:
    path: str
    url: str
    head_sha: str | None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/test_entities_remote_submodule.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add git_gui/domain/entities.py tests/domain/test_entities_remote_submodule.py
git commit -m "feat(domain): add Remote and Submodule entities"
```

---

## Task 2: Extend repository ports

**Files:**
- Modify: `git_gui/domain/ports.py`

- [ ] **Step 1: Add imports and reader methods**

In `git_gui/domain/ports.py`, update the entity import and `IRepositoryReader`:

Change line 4 to:
```python
from git_gui.domain.entities import Branch, Commit, CommitStat, FileStatus, Hunk, Remote, Stash, Submodule, Tag
```

Add inside `IRepositoryReader` (after `get_remote_tags`):
```python
    def list_remotes(self) -> list[Remote]: ...
    def list_submodules(self) -> list[Submodule]: ...
```

- [ ] **Step 2: Add writer methods**

Add inside `IRepositoryWriter` (after `push_tag`):
```python
    def add_remote(self, name: str, url: str) -> None: ...
    def remove_remote(self, name: str) -> None: ...
    def rename_remote(self, old_name: str, new_name: str) -> None: ...
    def set_remote_url(self, name: str, url: str) -> None: ...
    def add_submodule(self, path: str, url: str) -> None: ...
    def remove_submodule(self, path: str) -> None: ...
    def set_submodule_url(self, path: str, url: str) -> None: ...
```

- [ ] **Step 3: Verify import is clean**

Run: `uv run python -c "from git_gui.domain.ports import IRepositoryReader, IRepositoryWriter; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add git_gui/domain/ports.py
git commit -m "feat(domain): extend ports with remote/submodule methods"
```

---

## Task 3: Application query classes (ListRemotes, ListSubmodules)

**Files:**
- Modify: `git_gui/application/queries.py`
- Test: `tests/application/test_queries_remote_submodule.py`

- [ ] **Step 1: Write the failing test**

Create `tests/application/test_queries_remote_submodule.py`:

```python
from unittest.mock import MagicMock
from git_gui.domain.entities import Remote, Submodule
from git_gui.application.queries import ListRemotes, ListSubmodules


def test_list_remotes_calls_reader():
    reader = MagicMock()
    reader.list_remotes.return_value = [Remote("origin", "u", "u")]
    q = ListRemotes(reader)
    assert q.execute() == [Remote("origin", "u", "u")]
    reader.list_remotes.assert_called_once()


def test_list_submodules_calls_reader():
    reader = MagicMock()
    reader.list_submodules.return_value = [Submodule("libs/x", "u", "abc")]
    q = ListSubmodules(reader)
    assert q.execute() == [Submodule("libs/x", "u", "abc")]
    reader.list_submodules.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/application/test_queries_remote_submodule.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the query classes**

Update the import in `git_gui/application/queries.py` line 3 to include `Remote, Submodule`:
```python
from git_gui.domain.entities import Branch, Commit, CommitStat, FileStatus, Hunk, Remote, Stash, Submodule, Tag
```

Append to `git_gui/application/queries.py`:

```python
class ListRemotes:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> list[Remote]:
        return self._reader.list_remotes()


class ListSubmodules:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> list[Submodule]:
        return self._reader.list_submodules()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/application/test_queries_remote_submodule.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add git_gui/application/queries.py tests/application/test_queries_remote_submodule.py
git commit -m "feat(application): add ListRemotes and ListSubmodules queries"
```

---

## Task 4: Application command classes (remote + submodule mutations)

**Files:**
- Modify: `git_gui/application/commands.py`
- Test: `tests/application/test_commands_remote_submodule.py`

- [ ] **Step 1: Write the failing test**

Create `tests/application/test_commands_remote_submodule.py`:

```python
from unittest.mock import MagicMock
from git_gui.application.commands import (
    AddRemote, RemoveRemote, RenameRemote, SetRemoteUrl,
    AddSubmodule, RemoveSubmodule, SetSubmoduleUrl,
)


def test_add_remote():
    w = MagicMock()
    AddRemote(w).execute("origin", "git@x:a.git")
    w.add_remote.assert_called_once_with("origin", "git@x:a.git")


def test_remove_remote():
    w = MagicMock()
    RemoveRemote(w).execute("origin")
    w.remove_remote.assert_called_once_with("origin")


def test_rename_remote():
    w = MagicMock()
    RenameRemote(w).execute("origin", "upstream")
    w.rename_remote.assert_called_once_with("origin", "upstream")


def test_set_remote_url():
    w = MagicMock()
    SetRemoteUrl(w).execute("origin", "git@x:b.git")
    w.set_remote_url.assert_called_once_with("origin", "git@x:b.git")


def test_add_submodule():
    w = MagicMock()
    AddSubmodule(w).execute("libs/foo", "git@x:foo.git")
    w.add_submodule.assert_called_once_with("libs/foo", "git@x:foo.git")


def test_remove_submodule():
    w = MagicMock()
    RemoveSubmodule(w).execute("libs/foo")
    w.remove_submodule.assert_called_once_with("libs/foo")


def test_set_submodule_url():
    w = MagicMock()
    SetSubmoduleUrl(w).execute("libs/foo", "git@x:bar.git")
    w.set_submodule_url.assert_called_once_with("libs/foo", "git@x:bar.git")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/application/test_commands_remote_submodule.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the command classes**

Append to `git_gui/application/commands.py`:

```python
class AddRemote:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str, url: str) -> None:
        self._writer.add_remote(name, url)


class RemoveRemote:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str) -> None:
        self._writer.remove_remote(name)


class RenameRemote:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, old_name: str, new_name: str) -> None:
        self._writer.rename_remote(old_name, new_name)


class SetRemoteUrl:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str, url: str) -> None:
        self._writer.set_remote_url(name, url)


class AddSubmodule:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str, url: str) -> None:
        self._writer.add_submodule(path, url)


class RemoveSubmodule:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str) -> None:
        self._writer.remove_submodule(path)


class SetSubmoduleUrl:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str, url: str) -> None:
        self._writer.set_submodule_url(path, url)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/application/test_commands_remote_submodule.py -v`
Expected: 7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add git_gui/application/commands.py tests/application/test_commands_remote_submodule.py
git commit -m "feat(application): add remote/submodule mutation commands"
```

---

## Task 5: Wire new queries/commands into buses

**Files:**
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Update imports in bus.py**

Change the queries import block to include the two new queries:
```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes, GetTags, GetRemoteTags, GetCommitStats,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
    GetCommitDetail, IsDirty, GetHeadOid,
    ListRemotes, ListSubmodules,
)
```

Change the commands import block to include the seven new commands:
```python
from git_gui.application.commands import (
    StageFiles, UnstageFiles, CreateCommit,
    Checkout, CheckoutCommit, CheckoutRemoteBranch, CreateBranch, DeleteBranch,
    CreateTag, DeleteTag, PushTag,
    Merge, Rebase, Push, Pull, Fetch,
    Stash, PopStash, ApplyStash, DropStash,
    StageHunk, UnstageHunk, FetchAllPrune,
    DiscardFile, DiscardHunk,
    AddRemote, RemoveRemote, RenameRemote, SetRemoteUrl,
    AddSubmodule, RemoveSubmodule, SetSubmoduleUrl,
)
```

- [ ] **Step 2: Add fields to QueryBus**

In the `QueryBus` dataclass, add after `get_head_oid`:
```python
    list_remotes: ListRemotes
    list_submodules: ListSubmodules
```

In `QueryBus.from_reader`, add after `get_head_oid=GetHeadOid(reader),`:
```python
            list_remotes=ListRemotes(reader),
            list_submodules=ListSubmodules(reader),
```

- [ ] **Step 3: Add fields to CommandBus**

In the `CommandBus` dataclass, add after `fetch_all_prune`:
```python
    add_remote: AddRemote
    remove_remote: RemoveRemote
    rename_remote: RenameRemote
    set_remote_url: SetRemoteUrl
    add_submodule: AddSubmodule
    remove_submodule: RemoveSubmodule
    set_submodule_url: SetSubmoduleUrl
```

In `CommandBus.from_writer`, add after `fetch_all_prune=FetchAllPrune(writer),`:
```python
            add_remote=AddRemote(writer),
            remove_remote=RemoveRemote(writer),
            rename_remote=RenameRemote(writer),
            set_remote_url=SetRemoteUrl(writer),
            add_submodule=AddSubmodule(writer),
            remove_submodule=RemoveSubmodule(writer),
            set_submodule_url=SetSubmoduleUrl(writer),
```

- [ ] **Step 4: Verify buses construct cleanly**

Run:
```bash
uv run python -c "from git_gui.presentation.bus import QueryBus, CommandBus; from unittest.mock import MagicMock; QueryBus.from_reader(MagicMock()); CommandBus.from_writer(MagicMock()); print('ok')"
```
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/bus.py
git commit -m "feat(bus): register remote/submodule queries and commands"
```

---

## Task 6: Submodule CLI subprocess wrapper

**Files:**
- Create: `git_gui/infrastructure/submodule_cli.py`
- Test: `tests/infrastructure/test_submodule_cli.py`

- [ ] **Step 1: Write the failing test (uses real git binary + temp repos)**

Create `tests/infrastructure/test_submodule_cli.py`:

```python
import os
import subprocess
from pathlib import Path
import pytest

from git_gui.infrastructure.submodule_cli import (
    SubmoduleCli, SubmoduleCommandError,
)


def _run(cwd: str, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def parent_and_child(tmp_path: Path):
    child = tmp_path / "child"
    child.mkdir()
    _run(str(child), "init", "-q", "-b", "main")
    _run(str(child), "config", "user.email", "t@t")
    _run(str(child), "config", "user.name", "t")
    (child / "f.txt").write_text("hi")
    _run(str(child), "add", ".")
    _run(str(child), "commit", "-q", "-m", "init")

    parent = tmp_path / "parent"
    parent.mkdir()
    _run(str(parent), "init", "-q", "-b", "main")
    _run(str(parent), "config", "user.email", "t@t")
    _run(str(parent), "config", "user.name", "t")
    _run(str(parent), "config", "protocol.file.allow", "always")
    (parent / "r.txt").write_text("root")
    _run(str(parent), "add", ".")
    _run(str(parent), "commit", "-q", "-m", "root")
    return parent, child


def test_add_submodule_creates_gitmodules(parent_and_child):
    parent, child = parent_and_child
    cli = SubmoduleCli(str(parent))
    cli.add(path="libs/foo", url=str(child))
    assert (parent / ".gitmodules").exists()
    assert (parent / "libs" / "foo" / "f.txt").exists()


def test_set_url_updates_gitmodules(parent_and_child):
    parent, child = parent_and_child
    cli = SubmoduleCli(str(parent))
    cli.add(path="libs/foo", url=str(child))
    new_url = str(child) + "#renamed"
    cli.set_url("libs/foo", new_url)
    text = (parent / ".gitmodules").read_text()
    assert "renamed" in text


def test_remove_clears_submodule(parent_and_child):
    parent, child = parent_and_child
    cli = SubmoduleCli(str(parent))
    cli.add(path="libs/foo", url=str(child))
    cli.remove("libs/foo")
    assert not (parent / "libs" / "foo").exists()
    gm = parent / ".gitmodules"
    if gm.exists():
        assert "libs/foo" not in gm.read_text()


def test_missing_git_raises_friendly_error(parent_and_child, monkeypatch):
    parent, _ = parent_and_child
    cli = SubmoduleCli(str(parent), git_executable="definitely-not-git-xyz")
    with pytest.raises(SubmoduleCommandError) as ei:
        cli.add(path="libs/foo", url="anything")
    assert "not found" in str(ei.value).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_submodule_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'git_gui.infrastructure.submodule_cli'`.

- [ ] **Step 3: Implement the wrapper**

Create `git_gui/infrastructure/submodule_cli.py`:

```python
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

from git_gui.resources import subprocess_kwargs


class SubmoduleCommandError(Exception):
    """Raised when a `git submodule` (or related) CLI call fails."""


class SubmoduleCli:
    """Thin wrapper around `git submodule` operations executed via subprocess.

    pygit2 lacks reliable support for submodule add/remove/url-change, so we
    shell out to the `git` CLI. The repo working directory is used as cwd.
    """

    def __init__(self, repo_workdir: str, git_executable: str = "git") -> None:
        self._cwd = repo_workdir
        self._git = git_executable

    def _run(self, *args: str) -> None:
        if shutil.which(self._git) is None:
            raise SubmoduleCommandError(
                f"`{self._git}` executable not found on PATH"
            )
        try:
            subprocess.run(
                [self._git, *args],
                cwd=self._cwd,
                check=True,
                capture_output=True,
                text=True,
                **subprocess_kwargs(),
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip() or (e.stdout or "").strip() or str(e)
            raise SubmoduleCommandError(stderr) from e
        except FileNotFoundError as e:
            raise SubmoduleCommandError(
                f"`{self._git}` executable not found on PATH"
            ) from e

    def add(self, path: str, url: str) -> None:
        self._run("submodule", "add", "--", url, path)

    def set_url(self, path: str, url: str) -> None:
        # Update .gitmodules then sync into .git/config of the submodule.
        self._run("config", "-f", ".gitmodules", f"submodule.{path}.url", url)
        self._run("submodule", "sync", "--", path)

    def remove(self, path: str) -> None:
        # Standard 3-step removal.
        self._run("submodule", "deinit", "-f", "--", path)
        self._run("rm", "-f", "--", path)
        modules_dir = Path(self._cwd) / ".git" / "modules" / path
        if modules_dir.exists():
            import shutil as _sh
            _sh.rmtree(modules_dir, ignore_errors=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/infrastructure/test_submodule_cli.py -v`
Expected: 4 PASSED. (If `git` is not installed locally, the first three tests will be skipped/fail — install `git` first.)

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/submodule_cli.py tests/infrastructure/test_submodule_cli.py
git commit -m "feat(infra): add SubmoduleCli subprocess wrapper"
```

---

## Task 7: pygit2 repository — implement remote CRUD

**Files:**
- Modify: `git_gui/infrastructure/pygit2_repo.py`
- Test: `tests/infrastructure/test_pygit2_repo_remotes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/infrastructure/test_pygit2_repo_remotes.py`:

```python
import subprocess
from pathlib import Path
import pytest

from git_gui.infrastructure.pygit2_repo import Pygit2Repository


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def repo(tmp_path: Path):
    p = tmp_path / "r"
    p.mkdir()
    _run(str(p), "init", "-q", "-b", "main")
    _run(str(p), "config", "user.email", "t@t")
    _run(str(p), "config", "user.name", "t")
    (p / "f.txt").write_text("hi")
    _run(str(p), "add", ".")
    _run(str(p), "commit", "-q", "-m", "init")
    return Pygit2Repository(str(p))


def test_list_remotes_empty(repo):
    assert repo.list_remotes() == []


def test_add_then_list_remote(repo):
    repo.add_remote("origin", "git@example.com:a.git")
    remotes = repo.list_remotes()
    assert len(remotes) == 1
    assert remotes[0].name == "origin"
    assert remotes[0].fetch_url == "git@example.com:a.git"
    assert remotes[0].push_url == "git@example.com:a.git"


def test_rename_remote(repo):
    repo.add_remote("origin", "git@example.com:a.git")
    repo.rename_remote("origin", "upstream")
    names = [r.name for r in repo.list_remotes()]
    assert names == ["upstream"]


def test_set_remote_url(repo):
    repo.add_remote("origin", "git@example.com:a.git")
    repo.set_remote_url("origin", "git@example.com:b.git")
    assert repo.list_remotes()[0].fetch_url == "git@example.com:b.git"


def test_remove_remote(repo):
    repo.add_remote("origin", "git@example.com:a.git")
    repo.remove_remote("origin")
    assert repo.list_remotes() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_pygit2_repo_remotes.py -v`
Expected: FAIL with `AttributeError: 'Pygit2Repository' object has no attribute 'list_remotes'`.

- [ ] **Step 3: Implement remote methods**

Add to `git_gui/infrastructure/pygit2_repo.py` (inside `Pygit2Repository`). Also update the entities import at the top of the file to add `Remote, Submodule`:

```python
from git_gui.domain.entities import (
    Branch, Commit, CommitStat, FileStat, FileStatus, Hunk, Remote, Stash, Submodule, Tag, WORKING_TREE_OID,
)
```

Add these methods inside the class:

```python
    # ----- Remotes -----

    def list_remotes(self) -> list[Remote]:
        result: list[Remote] = []
        for r in self._repo.remotes:
            push_url = r.push_url if r.push_url else r.url
            result.append(Remote(name=r.name, fetch_url=r.url, push_url=push_url))
        return result

    def add_remote(self, name: str, url: str) -> None:
        self._repo.remotes.create(name, url)

    def remove_remote(self, name: str) -> None:
        self._repo.remotes.delete(name)

    def rename_remote(self, old_name: str, new_name: str) -> None:
        self._repo.remotes.rename(old_name, new_name)

    def set_remote_url(self, name: str, url: str) -> None:
        self._repo.remotes.set_url(name, url)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/infrastructure/test_pygit2_repo_remotes.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_pygit2_repo_remotes.py
git commit -m "feat(infra): implement remote CRUD on Pygit2Repository"
```

---

## Task 8: pygit2 repository — implement submodule list + delegate mutations

**Files:**
- Modify: `git_gui/infrastructure/pygit2_repo.py`
- Test: `tests/infrastructure/test_pygit2_repo_submodules.py`

- [ ] **Step 1: Write the failing test**

Create `tests/infrastructure/test_pygit2_repo_submodules.py`:

```python
import subprocess
from pathlib import Path
import pytest

from git_gui.infrastructure.pygit2_repo import Pygit2Repository


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture
def parent_repo(tmp_path: Path):
    child = tmp_path / "child"
    child.mkdir()
    _run(str(child), "init", "-q", "-b", "main")
    _run(str(child), "config", "user.email", "t@t")
    _run(str(child), "config", "user.name", "t")
    (child / "f.txt").write_text("hi")
    _run(str(child), "add", ".")
    _run(str(child), "commit", "-q", "-m", "init")

    parent = tmp_path / "parent"
    parent.mkdir()
    _run(str(parent), "init", "-q", "-b", "main")
    _run(str(parent), "config", "user.email", "t@t")
    _run(str(parent), "config", "user.name", "t")
    _run(str(parent), "config", "protocol.file.allow", "always")
    (parent / "r.txt").write_text("root")
    _run(str(parent), "add", ".")
    _run(str(parent), "commit", "-q", "-m", "root")
    return Pygit2Repository(str(parent)), str(child), parent


def test_list_submodules_empty(parent_repo):
    repo, _, _ = parent_repo
    assert repo.list_submodules() == []


def test_add_then_list_submodule(parent_repo):
    repo, child_url, parent_path = parent_repo
    repo.add_submodule("libs/foo", child_url)
    subs = repo.list_submodules()
    assert len(subs) == 1
    assert subs[0].path == "libs/foo"
    assert subs[0].url == child_url
    assert subs[0].head_sha is not None


def test_set_submodule_url(parent_repo):
    repo, child_url, parent_path = parent_repo
    repo.add_submodule("libs/foo", child_url)
    new_url = child_url + "#renamed"
    repo.set_submodule_url("libs/foo", new_url)
    text = (parent_path / ".gitmodules").read_text()
    assert "renamed" in text


def test_remove_submodule(parent_repo):
    repo, child_url, parent_path = parent_repo
    repo.add_submodule("libs/foo", child_url)
    repo.remove_submodule("libs/foo")
    assert repo.list_submodules() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_pygit2_repo_submodules.py -v`
Expected: FAIL with `AttributeError: 'Pygit2Repository' object has no attribute 'list_submodules'`.

- [ ] **Step 3: Implement submodule methods**

Add to `Pygit2Repository`:

```python
    # ----- Submodules -----

    def _submodule_cli(self):
        from git_gui.infrastructure.submodule_cli import SubmoduleCli
        return SubmoduleCli(self._repo.workdir)

    def list_submodules(self) -> list[Submodule]:
        result: list[Submodule] = []
        try:
            sm_paths = list(self._repo.listall_submodules())
        except Exception:
            return result
        for path in sm_paths:
            try:
                sm = self._repo.lookup_submodule(path)
                url = sm.url or ""
                head = str(sm.head_id) if sm.head_id is not None else None
            except Exception:
                url = ""
                head = None
            result.append(Submodule(path=path, url=url, head_sha=head))
        return result

    def add_submodule(self, path: str, url: str) -> None:
        self._submodule_cli().add(path=path, url=url)

    def remove_submodule(self, path: str) -> None:
        self._submodule_cli().remove(path)

    def set_submodule_url(self, path: str, url: str) -> None:
        self._submodule_cli().set_url(path, url)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/infrastructure/test_pygit2_repo_submodules.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_pygit2_repo_submodules.py
git commit -m "feat(infra): implement submodule listing and CLI-backed mutations"
```

---

## Task 9: RemoteDialog (presentation)

**Files:**
- Create: `git_gui/presentation/dialogs/remote_dialog.py`
- Test: `tests/presentation/dialogs/test_remote_dialog.py`

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/dialogs/test_remote_dialog.py`:

```python
from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Remote
from git_gui.presentation.dialogs.remote_dialog import RemoteDialog


@pytest.fixture
def buses():
    queries = MagicMock()
    commands = MagicMock()
    queries.list_remotes.execute.return_value = [
        Remote("origin", "git@x:a.git", "git@x:a.git"),
    ]
    return queries, commands


def test_dialog_populates_table_from_query(qtbot, buses):
    queries, commands = buses
    d = RemoteDialog(queries, commands)
    qtbot.addWidget(d)
    assert d._table.rowCount() == 1
    assert d._table.item(0, 0).text() == "origin"
    assert d._table.item(0, 1).text() == "git@x:a.git"


def test_remove_calls_command_and_refreshes(qtbot, buses):
    queries, commands = buses
    d = RemoteDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        d._on_remove()
    commands.remove_remote.execute.assert_called_once_with("origin")
    # refresh re-queries
    assert queries.list_remotes.execute.call_count >= 2


def test_error_shows_messagebox(qtbot, buses):
    queries, commands = buses
    commands.remove_remote.execute.side_effect = RuntimeError("boom")
    d = RemoteDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
         patch.object(QMessageBox, "warning") as warn:
        d._on_remove()
    warn.assert_called_once()
    assert "boom" in warn.call_args[0][2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/presentation/dialogs/test_remote_dialog.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement RemoteDialog**

Create `git_gui/presentation/dialogs/remote_dialog.py`:

```python
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class _RemoteEditDialog(QDialog):
    def __init__(self, parent=None, name: str = "", url: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Remote" if name else "Add Remote")
        self._name = QLineEdit(name)
        self._url = QLineEdit(url)
        form = QFormLayout()
        form.addRow("Name:", self._name)
        form.addRow("URL:", self._url)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self._name.text().strip(), self._url.text().strip()


class RemoteDialog(QDialog):
    def __init__(self, queries, commands, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remotes")
        self.resize(560, 360)
        self._queries = queries
        self._commands = commands

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Name", "Fetch URL", "Push URL"])
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)

        self._add_btn = QPushButton("Add...")
        self._edit_btn = QPushButton("Edit...")
        self._remove_btn = QPushButton("Remove")
        self._close_btn = QPushButton("Close")

        self._add_btn.clicked.connect(self._on_add)
        self._edit_btn.clicked.connect(self._on_edit)
        self._remove_btn.clicked.connect(self._on_remove)
        self._close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._edit_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addLayout(btn_row)

        self._refresh()

    def _refresh(self) -> None:
        try:
            remotes = self._queries.list_remotes.execute()
        except Exception as e:
            QMessageBox.warning(self, "Load remotes failed", str(e))
            remotes = []
        self._table.setRowCount(0)
        for r in remotes:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(r.name))
            self._table.setItem(row, 1, QTableWidgetItem(r.fetch_url))
            self._table.setItem(row, 2, QTableWidgetItem(r.push_url))

    def _selected_name(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 0).text()

    def _selected_url(self) -> str:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return ""
        return self._table.item(rows[0].row(), 1).text()

    def _on_add(self) -> None:
        d = _RemoteEditDialog(self)
        if d.exec() != QDialog.Accepted:
            return
        name, url = d.values()
        if not name or not url:
            QMessageBox.warning(self, "Invalid input", "Name and URL are required.")
            return
        try:
            self._commands.add_remote.execute(name, url)
        except Exception as e:
            QMessageBox.warning(self, "Add remote failed", str(e))
        self._refresh()

    def _on_edit(self) -> None:
        name = self._selected_name()
        if not name:
            return
        url = self._selected_url()
        d = _RemoteEditDialog(self, name=name, url=url)
        if d.exec() != QDialog.Accepted:
            return
        new_name, new_url = d.values()
        if not new_name or not new_url:
            QMessageBox.warning(self, "Invalid input", "Name and URL are required.")
            return
        try:
            if new_name != name:
                self._commands.rename_remote.execute(name, new_name)
            if new_url != url:
                self._commands.set_remote_url.execute(new_name, new_url)
        except Exception as e:
            QMessageBox.warning(self, "Edit remote failed", str(e))
        self._refresh()

    def _on_remove(self) -> None:
        name = self._selected_name()
        if not name:
            return
        if QMessageBox.question(self, "Remove remote", f"Remove remote '{name}'?") != QMessageBox.Yes:
            return
        try:
            self._commands.remove_remote.execute(name)
        except Exception as e:
            QMessageBox.warning(self, "Remove remote failed", str(e))
        self._refresh()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/presentation/dialogs/test_remote_dialog.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/dialogs/remote_dialog.py tests/presentation/dialogs/test_remote_dialog.py
git commit -m "feat(presentation): add RemoteDialog"
```

---

## Task 10: SubmoduleDialog (presentation)

**Files:**
- Create: `git_gui/presentation/dialogs/submodule_dialog.py`
- Test: `tests/presentation/dialogs/test_submodule_dialog.py`

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/dialogs/test_submodule_dialog.py`:

```python
from unittest.mock import MagicMock, patch
import os
import pytest
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Submodule
from git_gui.presentation.dialogs.submodule_dialog import SubmoduleDialog


@pytest.fixture
def buses():
    queries = MagicMock()
    commands = MagicMock()
    queries.list_submodules.execute.return_value = [
        Submodule("libs/foo", "git@x:foo.git", "abcdef1234"),
    ]
    return queries, commands


def test_dialog_populates_table(qtbot, buses):
    queries, commands = buses
    d = SubmoduleDialog(queries, commands, repo_workdir="/tmp/parent")
    qtbot.addWidget(d)
    assert d._table.rowCount() == 1
    assert d._table.item(0, 0).text() == "libs/foo"
    assert d._table.item(0, 1).text() == "git@x:foo.git"


def test_remove_calls_command(qtbot, buses):
    queries, commands = buses
    d = SubmoduleDialog(queries, commands, repo_workdir="/tmp/parent")
    qtbot.addWidget(d)
    d._table.selectRow(0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        d._on_remove()
    commands.remove_submodule.execute.assert_called_once_with("libs/foo")


def test_open_emits_absolute_path(qtbot, buses):
    queries, commands = buses
    d = SubmoduleDialog(queries, commands, repo_workdir="/tmp/parent")
    qtbot.addWidget(d)
    d._table.selectRow(0)
    captured: list[str] = []
    d.submoduleOpenRequested.connect(captured.append)
    d._on_open()
    assert len(captured) == 1
    assert captured[0].replace("\\", "/").endswith("parent/libs/foo")


def test_error_shows_messagebox(qtbot, buses):
    queries, commands = buses
    commands.remove_submodule.execute.side_effect = RuntimeError("boom")
    d = SubmoduleDialog(queries, commands, repo_workdir="/tmp/parent")
    qtbot.addWidget(d)
    d._table.selectRow(0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
         patch.object(QMessageBox, "warning") as warn:
        d._on_remove()
    warn.assert_called_once()
    assert "boom" in warn.call_args[0][2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/presentation/dialogs/test_submodule_dialog.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement SubmoduleDialog**

Create `git_gui/presentation/dialogs/submodule_dialog.py`:

```python
from __future__ import annotations
import os
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class _SubmoduleAddDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Submodule")
        self._path = QLineEdit()
        self._url = QLineEdit()
        form = QFormLayout()
        form.addRow("Path:", self._path)
        form.addRow("URL:", self._url)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self._path.text().strip(), self._url.text().strip()


class _SubmoduleUrlDialog(QDialog):
    def __init__(self, parent=None, url: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Submodule URL")
        self._url = QLineEdit(url)
        form = QFormLayout()
        form.addRow("URL:", self._url)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def value(self) -> str:
        return self._url.text().strip()


class SubmoduleDialog(QDialog):
    submoduleOpenRequested = Signal(str)

    def __init__(self, queries, commands, repo_workdir: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Submodules")
        self.resize(640, 380)
        self._queries = queries
        self._commands = commands
        self._workdir = repo_workdir

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Path", "URL", "HEAD"])
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)

        self._add_btn = QPushButton("Add...")
        self._edit_btn = QPushButton("Edit URL...")
        self._remove_btn = QPushButton("Remove")
        self._open_btn = QPushButton("Open")
        self._close_btn = QPushButton("Close")

        self._add_btn.clicked.connect(self._on_add)
        self._edit_btn.clicked.connect(self._on_edit)
        self._remove_btn.clicked.connect(self._on_remove)
        self._open_btn.clicked.connect(self._on_open)
        self._close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._edit_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addWidget(self._open_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addLayout(btn_row)

        self._refresh()

    def _refresh(self) -> None:
        try:
            subs = self._queries.list_submodules.execute()
        except Exception as e:
            QMessageBox.warning(self, "Load submodules failed", str(e))
            subs = []
        self._table.setRowCount(0)
        for s in subs:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(s.path))
            self._table.setItem(row, 1, QTableWidgetItem(s.url))
            self._table.setItem(row, 2, QTableWidgetItem((s.head_sha or "")[:10]))

    def _selected_path(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 0).text()

    def _selected_url(self) -> str:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return ""
        return self._table.item(rows[0].row(), 1).text()

    def _on_add(self) -> None:
        d = _SubmoduleAddDialog(self)
        if d.exec() != QDialog.Accepted:
            return
        path, url = d.values()
        if not path or not url:
            QMessageBox.warning(self, "Invalid input", "Path and URL are required.")
            return
        try:
            self._commands.add_submodule.execute(path, url)
        except Exception as e:
            QMessageBox.warning(self, "Add submodule failed", str(e))
        self._refresh()

    def _on_edit(self) -> None:
        path = self._selected_path()
        if not path:
            return
        d = _SubmoduleUrlDialog(self, url=self._selected_url())
        if d.exec() != QDialog.Accepted:
            return
        url = d.value()
        if not url:
            QMessageBox.warning(self, "Invalid input", "URL is required.")
            return
        try:
            self._commands.set_submodule_url.execute(path, url)
        except Exception as e:
            QMessageBox.warning(self, "Edit submodule failed", str(e))
        self._refresh()

    def _on_remove(self) -> None:
        path = self._selected_path()
        if not path:
            return
        if QMessageBox.question(self, "Remove submodule", f"Remove submodule '{path}'?") != QMessageBox.Yes:
            return
        try:
            self._commands.remove_submodule.execute(path)
        except Exception as e:
            QMessageBox.warning(self, "Remove submodule failed", str(e))
        self._refresh()

    def _on_open(self) -> None:
        path = self._selected_path()
        if not path:
            return
        abs_path = os.path.abspath(os.path.join(self._workdir, path))
        self.submoduleOpenRequested.emit(abs_path)
        self.accept()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/presentation/dialogs/test_submodule_dialog.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/dialogs/submodule_dialog.py tests/presentation/dialogs/test_submodule_dialog.py
git commit -m "feat(presentation): add SubmoduleDialog with open signal"
```

---

## Task 11: Git menu installer

**Files:**
- Create: `git_gui/presentation/menus/git_menu.py`
- Test: `tests/presentation/menus/test_git_menu.py`

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/menus/test_git_menu.py`:

```python
from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.menus.git_menu import install_git_menu


def test_install_git_menu_adds_two_actions(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    install_git_menu(window, queries=None, commands=None, repo_workdir=None,
                     on_open_submodule=lambda p: None)
    bar = window.menuBar()
    titles = [a.text() for a in bar.actions()]
    assert "&Git" in titles
    git_menu = next(a.menu() for a in bar.actions() if a.text() == "&Git")
    item_texts = [a.text() for a in git_menu.actions()]
    assert "&Remotes..." in item_texts
    assert "&Submodules..." in item_texts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/presentation/menus/test_git_menu.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement git_menu.py**

Create `git_gui/presentation/menus/git_menu.py`:

```python
"""Install a `Git` menu with `Remotes...` and `Submodules...` items."""
from __future__ import annotations
from typing import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.dialogs.remote_dialog import RemoteDialog
from git_gui.presentation.dialogs.submodule_dialog import SubmoduleDialog


def install_git_menu(
    window: QMainWindow,
    queries,
    commands,
    repo_workdir: str | None,
    on_open_submodule: Callable[[str], None],
) -> None:
    """Add a `Git` menu with `Remotes...` and `Submodules...` actions.

    `on_open_submodule` is invoked with the absolute path of the submodule
    when the user clicks Open in the submodule dialog.
    """
    bar = window.menuBar()
    git_menu = bar.addMenu("&Git")

    remote_action = QAction("&Remotes...", window)

    def _open_remote() -> None:
        if queries is None or commands is None:
            return
        RemoteDialog(queries, commands, window).exec()

    remote_action.triggered.connect(_open_remote)

    submodule_action = QAction("&Submodules...", window)

    def _open_submodule() -> None:
        if queries is None or commands is None or not repo_workdir:
            return
        d = SubmoduleDialog(queries, commands, repo_workdir, window)
        d.submoduleOpenRequested.connect(on_open_submodule)
        d.exec()

    submodule_action.triggered.connect(_open_submodule)

    git_menu.addAction(remote_action)
    git_menu.addAction(submodule_action)

    # Hold references to keep actions alive.
    window._git_remote_action = remote_action  # type: ignore[attr-defined]
    window._git_submodule_action = submodule_action  # type: ignore[attr-defined]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/presentation/menus/test_git_menu.py -v`
Expected: 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/menus/git_menu.py tests/presentation/menus/test_git_menu.py
git commit -m "feat(presentation): add install_git_menu installer"
```

---

## Task 12: Wire Git menu into MainWindow

**Files:**
- Modify: `git_gui/presentation/main_window.py`

- [ ] **Step 1: Add import**

Below `from git_gui.presentation.menus.appearance import install_appearance_menu` add:
```python
from git_gui.presentation.menus.git_menu import install_git_menu
```

- [ ] **Step 2: Install the menu in `__init__`**

In `MainWindow.__init__`, the handler method `_on_submodule_open_requested` (added in Step 3) must exist before being referenced. Add the install call near the END of `__init__`, just before `if self._queries is not None:` (around line 142). Insert:

```python
        install_git_menu(
            self,
            queries=self._queries,
            commands=self._commands,
            repo_workdir=self._repo_path,
            on_open_submodule=self._on_submodule_open_requested,
        )
```

- [ ] **Step 3: Add the open-submodule handler method**

Add this method to `MainWindow` (next to `_on_clone_completed`):

```python
    def _on_submodule_open_requested(self, abs_path: str) -> None:
        """Open a submodule as a top-level repo (one-way switch)."""
        self._repo_store.add_open(abs_path)
        self._repo_store.save()
        self._switch_repo(abs_path)
```

- [ ] **Step 4: Refresh the menu when switching repos**

The Git menu was installed once in `__init__` with the original `queries`/`commands`/`repo_path`. Since these change on `_switch_repo`, the menu's bound closures would still point at the originals. Fix by re-installing on switch.

In `_on_repo_ready`, after `self.setWindowTitle(f"GitCrisp — {path}")`, add:
```python
        # Re-install the Git menu so its actions bind to the new repo.
        bar = self.menuBar()
        for action in list(bar.actions()):
            if action.text() == "&Git":
                bar.removeAction(action)
        install_git_menu(
            self,
            queries=self._queries,
            commands=self._commands,
            repo_workdir=self._repo_path,
            on_open_submodule=self._on_submodule_open_requested,
        )
```

Also handle the empty state. In `_enter_empty_state`, after `self.setWindowTitle("GitCrisp")`, add:
```python
        bar = self.menuBar()
        for action in list(bar.actions()):
            if action.text() == "&Git":
                bar.removeAction(action)
        install_git_menu(
            self,
            queries=None,
            commands=None,
            repo_workdir=None,
            on_open_submodule=self._on_submodule_open_requested,
        )
```

- [ ] **Step 5: Smoke-check the import + construction**

Run:
```bash
uv run python -c "from git_gui.presentation.main_window import MainWindow; print('ok')"
```
Expected: `ok`.

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: all tests pass (no regressions).

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/main_window.py
git commit -m "feat(main-window): wire Git menu and submodule open handler"
```

---

## Final Verification

- [ ] **Run the full test suite one more time**

Run: `uv run pytest tests/ -v`
Expected: all green.

- [ ] **Manual smoke test**

Launch the app: `uv run python main.py`. Open any git repo. Verify:
1. Menubar shows a `Git` menu with `Remotes...` and `Submodules...`.
2. `Remotes...` opens a dialog listing existing remotes; Add/Edit/Remove work.
3. On a repo with submodules: `Submodules...` lists them; Add/Edit URL/Remove work; Open switches the window to the submodule repo.
4. Errors (e.g., adding a duplicate remote) show a `QMessageBox.warning` and the dialog stays open.

---

## Notes for the implementer

- All Python operations MUST run via `uv run` (per `CLAUDE.md`).
- Tests at `tests/infrastructure/` that exercise the real `git` CLI require `git` on PATH. CI must have it installed.
- Do NOT add fetch/prune/init/update buttons — that's explicitly out of scope (YAGNI).
- Do NOT add background threading; remote/submodule metadata ops are synchronous and fast. (Submodule add over network may be slow, but matches existing app behavior for clone, which is also blocking-ish in dialogs.)
- One-way "Open" — no back-navigation. The submodule replaces the current repo via the existing `_switch_repo` flow.
