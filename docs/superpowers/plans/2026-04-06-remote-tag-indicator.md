# Remote Tag Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a cloud icon next to sidebar tags that exist on the remote, with remote tag info cached to disk and updated on fetch.

**Architecture:** Add a `JsonRemoteTagCache` that persists remote tag names per repo to `~/.gitcrisp/remote_tags/`. Add `get_remote_tags()` to the infrastructure layer. After each fetch operation, query remote tags and update the cache. Sidebar reads the cache during reload and sets an icon on matching tags.

**Tech Stack:** Python 3.13, PySide6, pygit2, JSON file cache

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `git_gui/infrastructure/remote_tag_cache.py` | Create | JSON cache for remote tag names per repo |
| `git_gui/infrastructure/pygit2_repo.py` | Modify | Add `get_remote_tags(remote)` method |
| `git_gui/domain/ports.py` | Modify | Add `IRemoteTagCache` protocol, `get_remote_tags` to `IRepositoryReader` |
| `git_gui/presentation/widgets/sidebar.py` | Modify | Accept remote tag names, show cloud icon |
| `git_gui/presentation/main_window.py` | Modify | Pass cache to sidebar, update cache after fetch |
| `main.py` | Modify | Create cache instance and pass to MainWindow |
| `tests/infrastructure/test_remote_tag_cache.py` | Create | Cache read/write tests |
| `tests/infrastructure/test_reads.py` | Modify | Add get_remote_tags test |

---

### Task 1: Create JsonRemoteTagCache

**Files:**
- Create: `git_gui/infrastructure/remote_tag_cache.py`
- Create: `tests/infrastructure/test_remote_tag_cache.py`
- Modify: `git_gui/domain/ports.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_remote_tag_cache.py`:

```python
import json
import pytest
from pathlib import Path
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache


@pytest.fixture
def cache(tmp_path) -> JsonRemoteTagCache:
    return JsonRemoteTagCache(tmp_path / "remote_tags")


def test_load_returns_empty_when_no_file(cache):
    result = cache.load("/some/repo/path")
    assert result == {}


def test_save_and_load_roundtrip(cache):
    data = {"origin": ["v1.0.0", "v2.0.0"]}
    cache.save("/some/repo/path", data)
    result = cache.load("/some/repo/path")
    assert result == data


def test_different_repos_have_separate_caches(cache):
    cache.save("/repo/a", {"origin": ["v1.0"]})
    cache.save("/repo/b", {"origin": ["v2.0"]})
    assert cache.load("/repo/a") == {"origin": ["v1.0"]}
    assert cache.load("/repo/b") == {"origin": ["v2.0"]}


def test_save_creates_directory(tmp_path):
    cache_dir = tmp_path / "nested" / "remote_tags"
    cache = JsonRemoteTagCache(cache_dir)
    cache.save("/repo", {"origin": ["v1.0"]})
    assert cache.load("/repo") == {"origin": ["v1.0"]}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_remote_tag_cache.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Add IRemoteTagCache protocol to ports**

In `git_gui/domain/ports.py`, add after the `IRepoStore` protocol:

```python
@runtime_checkable
class IRemoteTagCache(Protocol):
    def load(self, repo_path: str) -> dict[str, list[str]]: ...
    def save(self, repo_path: str, data: dict[str, list[str]]) -> None: ...
```

- [ ] **Step 4: Create JsonRemoteTagCache**

Create `git_gui/infrastructure/remote_tag_cache.py`:

```python
from __future__ import annotations
import hashlib
import json
from pathlib import Path


class JsonRemoteTagCache:
    """Persists remote tag names per repo to JSON files."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._dir = cache_dir or Path.home() / ".gitcrisp" / "remote_tags"

    def _repo_file(self, repo_path: str) -> Path:
        repo_id = hashlib.sha256(repo_path.encode()).hexdigest()[:16]
        return self._dir / f"{repo_id}.json"

    def load(self, repo_path: str) -> dict[str, list[str]]:
        path = self._repo_file(repo_path)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, repo_path: str, data: dict[str, list[str]]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._repo_file(repo_path)
        path.write_text(json.dumps(data), encoding="utf-8")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_remote_tag_cache.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add git_gui/domain/ports.py git_gui/infrastructure/remote_tag_cache.py tests/infrastructure/test_remote_tag_cache.py
git commit -m "feat: add JsonRemoteTagCache for persisting remote tag names"
```

---

### Task 2: Add get_remote_tags to infrastructure

**Files:**
- Modify: `git_gui/infrastructure/pygit2_repo.py`
- Modify: `git_gui/domain/ports.py`
- Test: `tests/infrastructure/test_reads.py`

- [ ] **Step 1: Add get_remote_tags to IRepositoryReader**

In `git_gui/domain/ports.py`, add to `IRepositoryReader` after `get_tags`:

```python
    def get_remote_tags(self, remote: str) -> list[str]: ...
```

- [ ] **Step 2: Write the test**

Add to `tests/infrastructure/test_reads.py`:

```python
def test_get_remote_tags_no_remote(repo_impl):
    """Repos without remotes return an empty list."""
    tags = repo_impl.get_remote_tags("origin")
    assert tags == []
```

- [ ] **Step 3: Implement get_remote_tags**

Add to `Pygit2Repository` in the reads section, after `get_tags`:

```python
    def get_remote_tags(self, remote: str) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "ls-remote", "--tags", remote],
                capture_output=True, text=True,
                cwd=self._repo.workdir, **subprocess_kwargs(),
            )
            if result.returncode != 0:
                return []
            tags: list[str] = []
            for line in result.stdout.strip().splitlines():
                # Format: "<hash>\trefs/tags/<name>"
                parts = line.split("\t")
                if len(parts) != 2:
                    continue
                ref = parts[1]
                if not ref.startswith("refs/tags/"):
                    continue
                name = ref[len("refs/tags/"):]
                # Skip dereferenced entries like "v1.0^{}"
                if name.endswith("^{}"):
                    continue
                tags.append(name)
            return tags
        except Exception:
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_reads.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add git_gui/domain/ports.py git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_reads.py
git commit -m "feat: add get_remote_tags to infrastructure layer"
```

---

### Task 3: Sidebar cloud icon for remote tags

**Files:**
- Modify: `git_gui/presentation/widgets/sidebar.py`

- [ ] **Step 1: Update imports and add icon**

Add `QIcon` to the QtGui import and add the resources import:

```python
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QStandardItem, QStandardItemModel
from git_gui.resources import get_resource_path
```

Add a module-level constant after the existing constants:

```python
_CLOUD_ICON = None


def _get_cloud_icon() -> QIcon:
    global _CLOUD_ICON
    if _CLOUD_ICON is None:
        _CLOUD_ICON = QIcon(str(get_resource_path("arts") / "ic_cloud_done.svg"))
    return _CLOUD_ICON
```

- [ ] **Step 2: Update _LoadSignals**

```python
class _LoadSignals(QObject):
    done = Signal(list, list, list, set)  # branches, stashes, tags, remote_tag_names
```

- [ ] **Step 3: Add cache to constructor and reload**

Update `SidebarWidget.__init__` to accept and store the cache:

```python
    def __init__(self, queries: QueryBus, commands: CommandBus,
                 remote_tag_cache=None, repo_path: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands
        self._remote_tag_cache = remote_tag_cache
        self._repo_path = repo_path
```

Add a method to update the repo path when switching repos:

```python
    def set_repo_path(self, path: str | None) -> None:
        self._repo_path = path
```

- [ ] **Step 4: Update reload worker to load cache**

```python
    def reload(self) -> None:
        queries = self._queries

        signals = _LoadSignals()
        signals.done.connect(self._on_load_done)
        self._load_signals = signals  # prevent GC

        cache = self._remote_tag_cache
        repo_path = self._repo_path

        def _worker():
            branches = queries.get_branches.execute()
            stashes = queries.get_stashes.execute()
            tags = queries.get_tags.execute()
            remote_tag_names: set[str] = set()
            if cache and repo_path:
                data = cache.load(repo_path)
                for names in data.values():
                    remote_tag_names.update(names)
            signals.done.emit(branches, stashes, tags, remote_tag_names)

        threading.Thread(target=_worker, daemon=True).start()
```

- [ ] **Step 5: Update _on_load_done to show icons**

```python
    def _on_load_done(self, branches: list[Branch], stashes: list[Stash],
                      tags: list[Tag], remote_tag_names: set[str]) -> None:
        if self._queries is None:
            return

        self._model.clear()

        local = [b for b in branches if not b.is_remote]
        remote = [b for b in branches if b.is_remote]

        # Local branches — highlight HEAD
        local_header = QStandardItem("LOCAL BRANCHES")
        local_header.setEditable(False)
        local_header.setData("header", Qt.UserRole + 1)
        local_header.setSizeHint(QSize(0, _ROW_HEIGHT))
        for b in local:
            child = QStandardItem(b.name)
            child.setEditable(False)
            child.setData(b.name, Qt.UserRole)
            child.setData("branch", Qt.UserRole + 1)
            child.setData(b.target_oid, _TARGET_OID_ROLE)
            child.setSizeHint(QSize(0, _ROW_HEIGHT))
            if b.is_head:
                child.setData(True, _IS_HEAD_ROLE)
            local_header.appendRow(child)
        self._model.appendRow(local_header)

        # Remote branches
        self._add_section("REMOTE BRANCHES", [
            (b.name, b.name, "remote_branch", b.target_oid) for b in remote
        ])

        # Stashes
        self._add_section("STASHES", [
            (s.message, str(s.index), "stash", s.oid) for s in stashes
        ])

        # Tags — with cloud icon for remote tags
        tag_header = QStandardItem("TAGS")
        tag_header.setEditable(False)
        tag_header.setData("header", Qt.UserRole + 1)
        tag_header.setSizeHint(QSize(0, _ROW_HEIGHT))
        for t in tags:
            child = QStandardItem(t.name)
            child.setEditable(False)
            child.setData(t.name, Qt.UserRole)
            child.setData("tag", Qt.UserRole + 1)
            child.setData(t.target_oid, _TARGET_OID_ROLE)
            child.setSizeHint(QSize(0, _ROW_HEIGHT))
            if t.name in remote_tag_names:
                child.setIcon(_get_cloud_icon())
            tag_header.appendRow(child)
        self._model.appendRow(tag_header)

        self._tree.expandAll()
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/widgets/sidebar.py
git commit -m "feat: show cloud icon on sidebar tags that exist on remote"
```

---

### Task 4: Update fetch to refresh remote tag cache

**Files:**
- Modify: `git_gui/presentation/main_window.py`
- Modify: `main.py`

- [ ] **Step 1: Update main.py to create cache and pass it through**

In `main.py`, add the import:

```python
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
```

In the `main()` function, after creating `repo_store`, create the cache:

```python
    remote_tag_cache = JsonRemoteTagCache()
```

Update the `MainWindow` constructor call to pass the cache:

```python
    window = MainWindow(queries, commands, repo_store, remote_tag_cache, repo_path)
```

- [ ] **Step 2: Update MainWindow constructor**

Change the constructor signature:

```python
    def __init__(self, queries: QueryBus | None, commands: CommandBus | None,
                 repo_store: IRepoStore, remote_tag_cache, repo_path: str | None = None, parent=None) -> None:
```

Store the cache and repo path:

```python
        self._remote_tag_cache = remote_tag_cache
        self._repo_path = repo_path
```

Update sidebar construction to pass cache and repo path:

```python
        self._sidebar = SidebarWidget(queries, commands, remote_tag_cache, repo_path)
```

- [ ] **Step 3: Update fetch handlers to refresh cache after fetch**

Replace the sidebar fetch signal connection (around line 104):

```python
        self._sidebar.fetch_requested.connect(self._on_fetch_single)
```

Add the new handler method (near the other remote operation handlers):

```python
    def _on_fetch_single(self, remote: str) -> None:
        def _fn():
            self._commands.fetch.execute(remote)
            self._update_remote_tag_cache(remote)
        self._run_remote_op(f"Fetch {remote}", _fn)
```

Update `_on_fetch_all_prune`:

```python
    def _on_fetch_all_prune(self) -> None:
        def _fn():
            self._commands.fetch_all_prune.execute()
            self._update_remote_tag_cache("origin")
        self._run_remote_op("Fetch --all --prune", _fn)
```

Add the cache update helper:

```python
    def _update_remote_tag_cache(self, remote: str) -> None:
        if not self._remote_tag_cache or not self._repo_path or not self._queries:
            return
        try:
            remote_tags = self._queries.get_remote_tags.execute(remote)
            data = self._remote_tag_cache.load(self._repo_path)
            data[remote] = remote_tags
            self._remote_tag_cache.save(self._repo_path, data)
        except Exception:
            pass  # cache update failure is non-critical
```

- [ ] **Step 4: Update push tag handler to also refresh cache**

Replace the sidebar tag push signal connection (around line 128-129):

```python
        self._sidebar.tag_push_requested.connect(self._on_push_tag)
```

Add the handler:

```python
    def _on_push_tag(self, name: str) -> None:
        def _fn():
            self._commands.push_tag.execute("origin", name)
            self._update_remote_tag_cache("origin")
        self._run_remote_op(f"Push tag {name}", _fn)
```

- [ ] **Step 5: Update _switch_repo to pass repo path to sidebar**

In `_on_repo_ready`, add after `self._sidebar.set_buses(...)`:

```python
        self._repo_path = path
        self._sidebar.set_repo_path(path)
```

- [ ] **Step 6: Add get_remote_tags to QueryBus**

In `git_gui/application/queries.py`, add after `GetTags`:

```python
class GetRemoteTags:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, remote: str) -> list[str]:
        return self._reader.get_remote_tags(remote)
```

In `git_gui/presentation/bus.py`, add `GetRemoteTags` to imports:

```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes, GetTags, GetRemoteTags,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
    GetCommitDetail, IsDirty, GetHeadOid,
)
```

Add field to `QueryBus`:

```python
    get_remote_tags: GetRemoteTags
```

Add to `from_reader`:

```python
            get_remote_tags=GetRemoteTags(reader),
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add main.py git_gui/presentation/main_window.py git_gui/application/queries.py git_gui/presentation/bus.py
git commit -m "feat: update remote tag cache after fetch and push tag operations"
```

---

### Task 5: End-to-end verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Manual verification**

Run: `uv run python main.py`

Verify:
1. Open a repo with a remote that has tags
2. Tags in sidebar show NO icon initially (unless cache exists from prior fetch)
3. Click Fetch All — after fetch completes, sidebar reloads and tags that exist on remote show cloud icon
4. Create a new local tag — no cloud icon (it hasn't been pushed)
5. Push the new tag from sidebar context menu — after push, sidebar reloads and the tag now shows cloud icon
6. Switch repos — each repo has its own cache, icons update correctly
