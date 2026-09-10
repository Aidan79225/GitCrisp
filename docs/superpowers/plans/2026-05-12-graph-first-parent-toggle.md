# Graph First-Parent Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-repo toggle that switches the graph view into `git log --first-parent` mode — side-branch commits brought in by merges become invisible.

**Architecture:** Thread a keyword-only `first_parent: bool` flag through `IRepositoryReader.get_commits` (port) → `GetCommitGraph.execute` (application) → `CommitOps.get_commits` (pygit2), where it calls `walker.simplify_first_parent()` when set. Persist the per-repo state through a new generic `settings` dict on `JsonRepoStore` exposed via `get_repo_setting` / `set_repo_setting`. Add a checkable icon button to the graph header bar that reads/writes that setting and triggers `reload()`.

**Tech Stack:** Python 3.13 · pygit2 · PySide6 · pytest · pytest-qt · uv

**Spec:** `docs/superpowers/specs/2026-05-12-graph-first-parent-toggle-design.md`

---

## Task 0: Create feature branch

**Files:** none (git only).

- [ ] **Step 1: Create and switch to a new feature branch**

```bash
git checkout master
git pull --ff-only
git checkout -b feat/graph-first-parent-toggle
```

- [ ] **Step 2: Verify branch state**

Run: `git status; git log --oneline -3`
Expected: on `feat/graph-first-parent-toggle`, working tree clean, HEAD matches latest `origin/master`.

---

## Task 1: Data layer — thread `first_parent` flag (TDD)

**Files:**
- Modify: `git_gui/domain/ports.py`
- Modify: `git_gui/application/queries.py`
- Modify: `git_gui/infrastructure/pygit2/commit_ops.py` (lines 27–62)
- Test: `tests/infrastructure/test_reads.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/infrastructure/test_reads.py`:

```python
def test_get_commits_first_parent_excludes_side_branch_commits(repo_path):
    """With first_parent=True, commits brought in only via a merge's
    second parent must not appear in the listing."""
    import pygit2
    from git_gui.infrastructure.pygit2 import Pygit2Repository

    repo = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")

    # Layout:
    #   A (initial, from conftest fixture)
    #   |
    #   B  (master)
    #   |\
    #   | C   (feature)
    #   | |
    #   | D
    #   |/
    #   M  (master, merge of feature into master)
    head_a = repo.head.target

    # B on master
    (repo_path / "b.txt").write_text("b")
    repo.index.add("b.txt"); repo.index.write()
    tree = repo.index.write_tree()
    b_oid = repo.create_commit("refs/heads/master", sig, sig, "B", tree, [head_a])

    # Create feature branch off B
    repo.branches.local.create("feature", repo.get(b_oid))

    # C on feature
    repo.checkout("refs/heads/feature")
    (repo_path / "c.txt").write_text("c")
    repo.index.add("c.txt"); repo.index.write()
    tree = repo.index.write_tree()
    c_oid = repo.create_commit("refs/heads/feature", sig, sig, "C", tree, [b_oid])

    # D on feature
    (repo_path / "d.txt").write_text("d")
    repo.index.add("d.txt"); repo.index.write()
    tree = repo.index.write_tree()
    d_oid = repo.create_commit("refs/heads/feature", sig, sig, "D", tree, [c_oid])

    # Back to master, merge feature (no-ff via explicit merge commit)
    repo.checkout("refs/heads/master")
    # Merge: tree = merged index; parents = [master_tip, feature_tip]
    (repo_path / "c.txt").write_text("c")
    (repo_path / "d.txt").write_text("d")
    repo.index.add("c.txt"); repo.index.add("d.txt"); repo.index.write()
    tree = repo.index.write_tree()
    m_oid = repo.create_commit("refs/heads/master", sig, sig, "M", tree, [b_oid, d_oid])

    impl = Pygit2Repository(str(repo_path))

    # Full walk includes everyone.
    full = impl.get_commits(limit=100, first_parent=False)
    full_msgs = {c.message.strip() for c in full}
    assert {"M", "B", "C", "D", "Initial commit"}.issubset(full_msgs)

    # First-parent walk hides feature-only commits (C, D) but keeps M, B.
    fp = impl.get_commits(limit=100, first_parent=True)
    fp_msgs = {c.message.strip() for c in fp}
    assert "M" in fp_msgs
    assert "B" in fp_msgs
    assert "Initial commit" in fp_msgs
    assert "C" not in fp_msgs
    assert "D" not in fp_msgs
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_reads.py::test_get_commits_first_parent_excludes_side_branch_commits -v`
Expected: FAIL with `TypeError: get_commits() got an unexpected keyword argument 'first_parent'`.

- [ ] **Step 3: Add `first_parent` to the port**

Edit `git_gui/domain/ports.py`. Find the `get_commits` declaration in `IRepositoryReader` (currently around line 10) and add the keyword-only argument:

```python
def get_commits(
    self,
    limit: int,
    skip: int = 0,
    extra_tips: list[str] | None = None,
    *,
    first_parent: bool = False,
) -> list[Commit]: ...
```

- [ ] **Step 4: Pass the flag through the application layer**

Edit `git_gui/application/queries.py`. Update `GetCommitGraph.execute` (currently lines 12–13):

```python
class GetCommitGraph:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(
        self,
        limit: int = 200,
        skip: int = 0,
        extra_tips: list[str] | None = None,
        *,
        first_parent: bool = False,
    ) -> list[Commit]:
        return self._reader.get_commits(
            limit, skip, extra_tips=extra_tips, first_parent=first_parent,
        )
```

- [ ] **Step 5: Implement the flag in pygit2**

Edit `git_gui/infrastructure/pygit2/commit_ops.py`. Update the signature and body of `CommitOps.get_commits` (currently lines 27–62). Replace it with:

```python
def get_commits(
    self,
    limit: int,
    skip: int = 0,
    extra_tips: list[str] | None = None,
    *,
    first_parent: bool = False,
) -> list[Commit]:
    if self._repo.head_is_unborn:
        return []

    walker = self._repo.walk(
        self._repo.head.target,
        pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_TIME,
    )

    # Also push upstream remote branch if current branch has one
    try:
        head_ref = self._repo.head
        if not head_ref.name.startswith("refs/heads/"):
            pass  # detached HEAD — no upstream
        else:
            local_name = head_ref.name[len("refs/heads/"):]
            local_branch = self._repo.branches.local[local_name]
            if local_branch.upstream:
                walker.push(local_branch.upstream.resolve().target)
    except (KeyError, Exception):
        pass

    # Push extra tips (e.g. clicked branch)
    for tip in (extra_tips or []):
        try:
            walker.push(pygit2.Oid(hex=tip))
        except (ValueError, Exception):
            pass

    if first_parent:
        walker.simplify_first_parent()

    # Skip first N commits
    for _ in range(skip):
        try:
            next(walker)
        except StopIteration:
            return []
    return [_commit_to_entity(c) for c, _ in zip(walker, range(limit))]
```

(Only the new signature and the `if first_parent:` block are new — everything else is verbatim.)

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/infrastructure/test_reads.py::test_get_commits_first_parent_excludes_side_branch_commits -v`
Expected: PASS.

- [ ] **Step 7: Run the full infrastructure test file**

Run: `uv run pytest tests/infrastructure/test_reads.py -q`
Expected: all tests pass (existing + new).

- [ ] **Step 8: Commit**

```bash
git add git_gui/domain/ports.py git_gui/application/queries.py git_gui/infrastructure/pygit2/commit_ops.py tests/infrastructure/test_reads.py
git -c user.name="Aidan Wang" -c user.email="aidan79225@gmail.com" commit -m "feat(graph): thread first_parent flag through data layer

Adds a keyword-only first_parent=False argument to IRepositoryReader.get_commits, GetCommitGraph.execute, and the pygit2 CommitOps implementation. When set, the walker calls simplify_first_parent() so side-branch commits brought in by merges are excluded from the listing. No call sites change yet — that's the next task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Per-repo settings on `JsonRepoStore` (TDD)

**Files:**
- Modify: `git_gui/domain/ports.py`
- Modify: `git_gui/infrastructure/repo_store.py`
- Test: `tests/infrastructure/test_repo_store.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/infrastructure/test_repo_store.py`:

```python
class TestJsonRepoStoreSettings:
    def test_get_returns_default_when_missing(self, store):
        store.load()
        assert store.get_repo_setting("/repo/a", "first_parent", False) is False
        assert store.get_repo_setting("/repo/a", "missing", "fallback") == "fallback"

    def test_set_then_get_roundtrip(self, store):
        store.load()
        store.set_repo_setting("/repo/a", "first_parent", True)
        assert store.get_repo_setting("/repo/a", "first_parent", False) is True

    def test_settings_persist_through_save_and_reload(self, store, store_path):
        store.load()
        store.set_repo_setting("/repo/a", "first_parent", True)
        store.save()
        # Re-instantiate to confirm we read from disk, not memory.
        fresh = JsonRepoStore(store_path)
        fresh.load()
        assert fresh.get_repo_setting("/repo/a", "first_parent", False) is True

    def test_settings_survive_close_repo(self, store):
        store.load()
        store.add_open("/repo/a")
        store.set_repo_setting("/repo/a", "first_parent", True)
        store.close_repo("/repo/a")
        assert store.get_repo_setting("/repo/a", "first_parent", False) is True

    def test_settings_survive_remove_recent(self, store):
        store.load()
        store.add_open("/repo/a")
        store.set_repo_setting("/repo/a", "first_parent", True)
        store.close_repo("/repo/a")
        store.remove_recent("/repo/a")
        assert store.get_repo_setting("/repo/a", "first_parent", False) is True

    def test_old_file_without_settings_key_loads_clean(self, store, store_path):
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps({
            "open": [], "recent": [], "active": None,
        }))
        store.load()
        assert store.get_repo_setting("/repo/a", "first_parent", False) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_repo_store.py::TestJsonRepoStoreSettings -v`
Expected: FAIL with `AttributeError: 'JsonRepoStore' object has no attribute 'get_repo_setting'`.

- [ ] **Step 3: Implement settings in `JsonRepoStore`**

Edit `git_gui/infrastructure/repo_store.py`. Replace the entire file with:

```python
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

_RECENT_LIMIT = 20


class JsonRepoStore:
    """Persists open/recent repo lists and per-repo settings to a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path.home() / ".gitcrisp" / "repos.json"
        self._open: list[str] = []
        self._recent: list[str] = []
        self._active: str | None = None
        self._settings: dict[str, dict[str, Any]] = {}

    def load(self) -> None:
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._open = list(data.get("open", []))
            self._recent = list(data.get("recent", []))
            self._active = data.get("active")
            raw_settings = data.get("settings", {}) or {}
            self._settings = {
                str(k): dict(v) for k, v in raw_settings.items()
                if isinstance(v, dict)
            }
        else:
            self._open = []
            self._recent = []
            self._active = None
            self._settings = {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "open": self._open,
            "recent": self._recent,
            "active": self._active,
            "settings": self._settings,
        }
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_open_repos(self) -> list[str]:
        return list(self._open)

    def get_recent_repos(self) -> list[str]:
        return [r for r in self._recent if r not in self._open]

    def get_active(self) -> str | None:
        return self._active

    def add_open(self, path: str, after: str | None = None) -> None:
        if path in self._open:
            self._open.remove(path)
        if after and after in self._open:
            idx = self._open.index(after) + 1
            self._open.insert(idx, path)
        else:
            self._open.insert(0, path)
        if path in self._recent:
            self._recent.remove(path)
        self._active = path

    def close_repo(self, path: str) -> None:
        if path in self._open:
            self._open.remove(path)
        if path not in self._recent:
            self._recent.insert(0, path)
            self._recent = self._recent[:_RECENT_LIMIT]
        if self._active == path:
            self._active = None

    def remove_recent(self, path: str) -> None:
        if path in self._recent:
            self._recent.remove(path)

    def set_active(self, path: str) -> None:
        self._active = path

    def set_open_order(self, paths: list[str]) -> None:
        """Replace the open repos list with a new ordering."""
        self._open = list(paths)

    def get_repo_setting(self, path: str, key: str, default: Any = None) -> Any:
        return self._settings.get(path, {}).get(key, default)

    def set_repo_setting(self, path: str, key: str, value: Any) -> None:
        self._settings.setdefault(path, {})[key] = value
```

- [ ] **Step 4: Add the port methods to `IRepoStore`**

Edit `git_gui/domain/ports.py`. Find the existing `IRepoStore` Protocol (it's already imported by `MainWindow`). Add at the end of the protocol body:

```python
def get_repo_setting(self, path: str, key: str, default: object = None) -> object: ...
def set_repo_setting(self, path: str, key: str, value: object) -> None: ...
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_repo_store.py -v`
Expected: all tests pass (existing + new TestJsonRepoStoreSettings class).

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `uv run pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add git_gui/domain/ports.py git_gui/infrastructure/repo_store.py tests/infrastructure/test_repo_store.py
git -c user.name="Aidan Wang" -c user.email="aidan79225@gmail.com" commit -m "feat(repo-store): per-repo settings dict for view-mode prefs

Adds a generic settings dict to JsonRepoStore keyed by repo path, plus get_repo_setting / set_repo_setting accessors on the IRepoStore port. Backwards-compatible: pre-existing repos.json files load with an empty settings dict. Settings persist through close_repo and remove_recent — the user reopening the same path keeps their per-repo view prefs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Add the SVG icon

**Files:**
- Create: `arts/ic_first_parent.svg`

- [ ] **Step 1: Create the icon file**

Create `arts/ic_first_parent.svg` with this content:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <line x1="8" y1="3" x2="8" y2="21"/>
  <circle cx="8" cy="6" r="1.6" fill="currentColor"/>
  <circle cx="8" cy="12" r="1.6" fill="currentColor"/>
  <circle cx="8" cy="18" r="1.6" fill="currentColor"/>
  <path d="M8 12 C 13 12, 14 9, 16 8" stroke-opacity="0.35"/>
  <circle cx="16" cy="8" r="1.4" stroke-opacity="0.35"/>
</svg>
```

This is a mainline with three nodes plus a faded stub of a side branch — reads as "first-parent only."

- [ ] **Step 2: Verify the SVG loads via the same pipeline as other icons**

Run: `uv run python -c "from PySide6.QtCore import QSize; from PySide6.QtWidgets import QApplication; app=QApplication([]); from git_gui.presentation.widgets.graph import _tinted_icon, _ARTS; from PySide6.QtGui import QColor; ic=_tinted_icon(str(_ARTS / 'ic_first_parent.svg'), QColor('white')); pm=ic.pixmap(QSize(28,28)); print('OK' if not pm.isNull() else 'FAIL')"`
Expected: prints `OK`.

- [ ] **Step 3: Commit**

```bash
git add arts/ic_first_parent.svg
git -c user.name="Aidan Wang" -c user.email="aidan79225@gmail.com" commit -m "feat(arts): add ic_first_parent.svg for graph view toggle

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: GraphWidget — repo_store, _first_parent state, set_repo_path, toggle button (TDD)

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py`
- Test: `tests/presentation/widgets/test_graph_first_parent.py` (new file)

- [ ] **Step 1: Write the failing widget tests**

Create `tests/presentation/widgets/test_graph_first_parent.py`:

```python
"""Tests for the graph header's first-parent toggle button."""
from __future__ import annotations
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from git_gui.presentation.widgets.graph import GraphWidget


def _app():
    return QApplication.instance() or QApplication([])


def _make_queries() -> MagicMock:
    """A queries bus that returns benign empty values for the reload worker."""
    q = MagicMock()
    q.get_commit_graph.execute.return_value = []
    q.get_branches.execute.return_value = []
    q.get_tags.execute.return_value = []
    q.is_dirty.execute.return_value = False
    q.get_head_oid.execute.return_value = ""
    q.get_repo_state.execute.return_value = MagicMock(head_branch=None)
    q.get_merge_head.execute.return_value = None
    return q


def test_set_repo_path_reads_persisted_setting_and_syncs_button(qtbot):
    _app()
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = True
    queries = _make_queries()
    commands = MagicMock()

    w = GraphWidget(queries, commands, repo_store=repo_store)
    qtbot.addWidget(w)

    w.set_repo_path("/repo/a")

    repo_store.get_repo_setting.assert_called_with("/repo/a", "first_parent", False)
    assert w._first_parent is True
    assert w._first_parent_btn.isChecked() is True


def test_set_repo_path_none_resets_to_unchecked(qtbot):
    _app()
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = True
    queries = _make_queries()
    commands = MagicMock()

    w = GraphWidget(queries, commands, repo_store=repo_store)
    qtbot.addWidget(w)
    w.set_repo_path("/repo/a")  # primes _first_parent True
    assert w._first_parent is True

    w.set_repo_path(None)
    assert w._first_parent is False
    assert w._first_parent_btn.isChecked() is False


def test_toggling_button_persists_and_reloads(qtbot):
    _app()
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = False
    queries = _make_queries()
    commands = MagicMock()

    w = GraphWidget(queries, commands, repo_store=repo_store)
    qtbot.addWidget(w)
    w.set_repo_path("/repo/a")

    # User clicks the toggle.
    w._first_parent_btn.setChecked(True)

    repo_store.set_repo_setting.assert_called_with("/repo/a", "first_parent", True)
    repo_store.save.assert_called()
    assert w._first_parent is True
    # Reload is invoked via the worker thread on the queries bus; verify
    # at least one call to get_commit_graph.execute happened with first_parent=True.
    calls = queries.get_commit_graph.execute.call_args_list
    assert any(call.kwargs.get("first_parent") is True for call in calls), (
        f"expected at least one call with first_parent=True, got {calls}"
    )


def test_reload_passes_first_parent_flag(qtbot):
    """Without any toggle interaction, the reload worker still passes
    first_parent=<current state> (False by default)."""
    _app()
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = False
    queries = _make_queries()
    commands = MagicMock()

    w = GraphWidget(queries, commands, repo_store=repo_store)
    qtbot.addWidget(w)
    w.set_repo_path("/repo/a")

    w.reload()
    qtbot.wait(50)  # let the background worker run

    calls = queries.get_commit_graph.execute.call_args_list
    assert calls, "expected get_commit_graph.execute to be called by reload"
    assert all(call.kwargs.get("first_parent") is False for call in calls)


def test_toggle_with_no_repo_path_does_not_persist(qtbot):
    """If no repo is active, toggling shouldn't crash trying to persist."""
    _app()
    repo_store = MagicMock()
    repo_store.get_repo_setting.return_value = False
    queries = _make_queries()
    commands = MagicMock()

    w = GraphWidget(queries, commands, repo_store=repo_store)
    qtbot.addWidget(w)
    # Skip set_repo_path entirely — _repo_path is None.
    w._first_parent_btn.setChecked(True)

    repo_store.set_repo_setting.assert_not_called()
    repo_store.save.assert_not_called()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/presentation/widgets/test_graph_first_parent.py -v`
Expected: FAIL — `GraphWidget` constructor doesn't accept `repo_store`, no `_first_parent_btn` attribute, no `set_repo_path` method.

- [ ] **Step 3: Update `GraphWidget.__init__` to accept `repo_store` and initialize state**

Edit `git_gui/presentation/widgets/graph.py`. Find the imports section near the top and add (if not present):

```python
from git_gui.domain.ports import IRepoStore
```

Then update the `GraphWidget.__init__` signature and add the new state. Currently the signature is:

```python
def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
```

Change it to:

```python
def __init__(self, queries: QueryBus, commands: CommandBus, repo_store: IRepoStore, parent=None) -> None:
```

After `self._scroll_anchor_oid: str | None = None` (currently line ~213), add:

```python
        self._repo_store = repo_store
        self._repo_path: str | None = None
        self._first_parent = False
```

- [ ] **Step 4: Add the toggle button to the header bar**

Still in `graph.py`, in `__init__`, find the loop that builds the toolbar icon buttons (currently lines ~252-266 — the `for icon_name, tooltip, signal in [...]` block ending with `header_bar.addWidget(btn)`). Immediately after that loop, **before** `header_bar.addStretch()`, insert:

```python
        # First-parent view toggle (checkable)
        self._first_parent_btn = QPushButton()
        self._first_parent_btn.setFixedSize(QSize(36, 36))
        self._first_parent_btn.setIconSize(QSize(28, 28))
        self._first_parent_btn.setCheckable(True)
        self._first_parent_btn.setToolTip("Show first-parent history only")
        self._first_parent_btn.toggled.connect(self._on_first_parent_toggled)
        header_bar.addWidget(self._first_parent_btn)
        self._styled_buttons.append(self._first_parent_btn)
        self._tinted_button_icons.append((self._first_parent_btn, "ic_first_parent"))
```

- [ ] **Step 5: Add `set_repo_path` and the toggle handler**

Still in `graph.py`, immediately after the `set_buses` method (currently around line 308–324), add two new methods:

```python
    def set_repo_path(self, path: str | None) -> None:
        """Load the persisted first-parent setting for `path` and sync the
        toggle button silently. Call this BEFORE set_buses on repo switches
        so the first reload reflects the right mode."""
        self._repo_path = path
        if path is None:
            new_value = False
        else:
            new_value = bool(self._repo_store.get_repo_setting(path, "first_parent", False))
        self._first_parent = new_value
        # blockSignals to avoid re-entering the toggle handler.
        was_blocked = self._first_parent_btn.blockSignals(True)
        try:
            self._first_parent_btn.setChecked(new_value)
        finally:
            self._first_parent_btn.blockSignals(was_blocked)

    def _on_first_parent_toggled(self, checked: bool) -> None:
        self._first_parent = checked
        if self._repo_path is not None:
            self._repo_store.set_repo_setting(self._repo_path, "first_parent", checked)
            self._repo_store.save()
        # No-op if queries aren't wired up yet (empty state).
        if self._queries is not None:
            self.reload()
```

- [ ] **Step 6: Pass `first_parent` through both `get_commit_graph.execute` call sites**

Still in `graph.py`. Find the line in the `reload()` worker (currently line ~349):

```python
            commits = queries.get_commit_graph.execute(limit=effective_limit, extra_tips=effective_tips)
```

Change it to:

```python
            commits = queries.get_commit_graph.execute(limit=effective_limit, extra_tips=effective_tips, first_parent=fp)
```

To make `fp` available inside the worker closure, capture it just before the worker is defined. Find the lines just before `def _worker():` in `reload()` (after `queries = self._queries`):

```python
        queries = self._queries
        fp = self._first_parent

        signals = _LoadSignals()
```

Do the same in `_load_more()` (currently line ~533+). Capture `fp = self._first_parent` next to the existing `queries = self._queries` line, then update the worker's call (currently line ~543):

```python
            more = queries.get_commit_graph.execute(limit=PAGE_SIZE, skip=skip, extra_tips=self._extra_tips, first_parent=fp)
```

- [ ] **Step 7: Run the widget tests to verify they pass**

Run: `uv run pytest tests/presentation/widgets/test_graph_first_parent.py -v`
Expected: all 5 tests pass.

- [ ] **Step 8: Run the full suite to confirm no regression**

Run: `uv run pytest tests/ -q`
Expected: all tests pass — but **note**: there may be existing call sites that construct `GraphWidget` without `repo_store` (in MainWindow). Those will be fixed in Task 5. If `tests/` exercises MainWindow construction directly and fails here, proceed to Task 5 before commiting this task.

If only `tests/presentation/widgets/` and below are green and the MainWindow tests fail because of the new required `repo_store` arg — that's expected. Continue to Task 5.

- [ ] **Step 9: Commit**

```bash
git add git_gui/presentation/widgets/graph.py tests/presentation/widgets/test_graph_first_parent.py
git -c user.name="Aidan Wang" -c user.email="aidan79225@gmail.com" commit -m "feat(graph): add first-parent toggle button to header bar

New checkable QPushButton (ic_first_parent icon) sits between the Insight button and the right-side stretch. Clicking it toggles GraphWidget._first_parent, persists the value via IRepoStore.set_repo_setting (when a repo is active), and triggers reload(). Both get_commit_graph.execute call sites (reload() and _load_more()) now pass first_parent=self._first_parent. A new set_repo_path(path) hook loads the persisted value silently; MainWindow wiring follows in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Wire `repo_store` and `set_repo_path` into MainWindow + RepoLifecycleMixin

**Files:**
- Modify: `git_gui/presentation/main_window/main_window.py` (lines 87–98, around `_build_widgets`)
- Modify: `git_gui/presentation/main_window/repo_lifecycle.py` (in `_on_repo_ready` and `_enter_empty_state`)

- [ ] **Step 1: Pass `repo_store` to `GraphWidget` in MainWindow**

Edit `git_gui/presentation/main_window/main_window.py`. Find the line in `_build_widgets`:

```python
        self._graph = GraphWidget(self._queries, self._commands)
```

Change it to:

```python
        self._graph = GraphWidget(self._queries, self._commands, repo_store=self._repo_store)
```

- [ ] **Step 2: Prime the graph's repo path during construction**

Still in `main_window.py`, in `MainWindow.__init__`, find the block that runs after the wiring is complete (immediately before the `# Wire cross-widget signals` comment). The block currently ends with `self._wire_repo_lifecycle_signals()`. Add immediately after it, **before** the `# Wire cross-widget signals` line:

```python
        # Load any persisted graph view mode for the initial repo.
        self._graph.set_repo_path(self._repo_path)
```

This ensures the initial `_reload()` call further down sees the right `_first_parent` value.

- [ ] **Step 3: Update `_on_repo_ready` in RepoLifecycleMixin**

Edit `git_gui/presentation/main_window/repo_lifecycle.py`. Find `_on_repo_ready`. The current method calls `self._graph.set_buses(self._queries, self._commands)`. Add a `set_repo_path` call immediately **before** the `set_buses` call:

```python
        self._sidebar.set_buses(self._queries, self._commands)
        self._graph.set_repo_path(path)
        self._graph.set_buses(self._queries, self._commands)
```

(Order matters: `set_repo_path` updates `_first_parent`; `set_buses` then triggers `reload()` which uses that value.)

- [ ] **Step 4: Update `_enter_empty_state` in RepoLifecycleMixin**

Still in `repo_lifecycle.py`. Find `_enter_empty_state`. It currently has:

```python
        self._sidebar.set_buses(None, None)
        self._graph.set_buses(None, None)
```

Insert `set_repo_path(None)` before the graph's `set_buses`:

```python
        self._sidebar.set_buses(None, None)
        self._graph.set_repo_path(None)
        self._graph.set_buses(None, None)
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -q`
Expected: all tests pass (683 prior + 5 widget tests + 6 settings tests + 1 first-parent infra test = ~695).

- [ ] **Step 6: Manual smoke test**

Run: `uv run python main.py`

In any repo with merges visible:
1. Confirm the new icon button appears in the graph header (between Insight and the right stretch).
2. Click it — side-branch commits should disappear; the merge commits should remain as single rows.
3. Click again — full graph returns.
4. Toggle on, switch to a different repo (must already have merges), confirm THAT repo starts in its own persisted state (off, unless previously toggled on for that repo too).
5. Toggle on in repo A, close the app, relaunch, open repo A — toggle should still be on.

If a step fails, fix and re-run; do not commit until the smoke test passes.

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/main_window/main_window.py git_gui/presentation/main_window/repo_lifecycle.py
git -c user.name="Aidan Wang" -c user.email="aidan79225@gmail.com" commit -m "feat(main-window): wire repo_store + set_repo_path into GraphWidget

MainWindow now passes its repo_store into GraphWidget and calls set_repo_path during construction so the initial reload reflects the persisted first-parent mode. RepoLifecycleMixin calls set_repo_path before set_buses on repo switches and on empty-state entry, mirroring the established sidebar pattern.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Push and open PR

**Files:** none (git only).

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/graph-first-parent-toggle
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat(graph): first-parent view toggle" --body "$(cat <<'EOF'
## Summary
- Adds a checkable icon button to the graph header that switches the view into \`git log --first-parent\` mode — side-branch commits brought in by merges become invisible.
- Setting is persisted per-repo via a new generic settings dict on JsonRepoStore (\`get_repo_setting\`/\`set_repo_setting\`), so each repo remembers its own view mode across launches.
- Pure additive wiring in the data layer: \`IRepositoryReader.get_commits\` / \`GetCommitGraph.execute\` / pygit2 \`CommitOps.get_commits\` gain a keyword-only \`first_parent=False\` argument; existing call sites are unchanged.

## Test plan
- [x] \`uv run pytest tests/ -q\` — all tests pass (existing + new infra/repo-store/widget tests for the toggle).
- [ ] Manual: in a repo with merges visible, toggle the button — side-branch commits disappear, merge commits remain.
- [ ] Manual: toggle on in repo A, switch to repo B (different state expected), switch back to repo A → state preserved.
- [ ] Manual: restart the app, reopen repo A → toggle state restored from disk.

Spec: \`docs/superpowers/specs/2026-05-12-graph-first-parent-toggle-design.md\`
Plan: \`docs/superpowers/plans/2026-05-12-graph-first-parent-toggle.md\`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: prints the PR URL.

---

## Verification summary

After Task 5 step 5, the test counts should be approximately:
- Infrastructure: +1 (first_parent test) +6 (settings tests) = +7
- Widget: +5 (graph first_parent tests) = +5
- **Grand total:** ~695 tests passing (was 683).

End-to-end manual verification per Task 5 step 6 must pass before opening the PR.
