# Sidebar Repo Switcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the left sidebar into branches (top) + repo list (bottom), enabling in-place repo switching with persistent open/recent repo lists.

**Architecture:** New `IRepoStore` domain protocol backed by `JsonRepoStore` (infrastructure) for persisting open/recent repos to `~/.gitstack/repos.json`. New `RepoListWidget` (presentation) for the repo list UI. MainWindow gains `_switch_repo()` to hot-swap the `Pygit2Repository` and buses across all widgets.

**Tech Stack:** Python 3.13+, PySide6, pygit2, pytest

---

### Task 1: IRepoStore Domain Protocol

**Files:**
- Modify: `git_gui/domain/ports.py:1-36`

- [ ] **Step 1: Add IRepoStore protocol**

Append after the existing `IRepositoryWriter` protocol in `git_gui/domain/ports.py`:

```python
@runtime_checkable
class IRepoStore(Protocol):
    def load(self) -> None: ...
    def save(self) -> None: ...
    def get_open_repos(self) -> list[str]: ...
    def get_recent_repos(self) -> list[str]: ...
    def get_active(self) -> str | None: ...
    def add_open(self, path: str) -> None: ...
    def close_repo(self, path: str) -> None: ...
    def remove_recent(self, path: str) -> None: ...
    def set_active(self, path: str) -> None: ...
```

- [ ] **Step 2: Commit**

```bash
git add git_gui/domain/ports.py
git commit -m "feat: add IRepoStore protocol to domain ports"
```

---

### Task 2: JsonRepoStore Implementation

**Files:**
- Create: `git_gui/infrastructure/repo_store.py`
- Create: `tests/infrastructure/test_repo_store.py`

- [ ] **Step 1: Write failing tests**

Create `tests/infrastructure/test_repo_store.py`:

```python
import json
import pytest
from pathlib import Path
from git_gui.infrastructure.repo_store import JsonRepoStore


@pytest.fixture
def store_path(tmp_path) -> Path:
    return tmp_path / ".gitstack" / "repos.json"


@pytest.fixture
def store(store_path) -> JsonRepoStore:
    return JsonRepoStore(store_path)


class TestJsonRepoStoreLoad:
    def test_load_missing_file_returns_empty_state(self, store):
        store.load()
        assert store.get_open_repos() == []
        assert store.get_recent_repos() == []
        assert store.get_active() is None

    def test_load_existing_file(self, store, store_path):
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps({
            "open": ["/repo/a", "/repo/b"],
            "recent": ["/repo/c"],
            "active": "/repo/a",
        }))
        store.load()
        assert store.get_open_repos() == ["/repo/a", "/repo/b"]
        assert store.get_recent_repos() == ["/repo/c"]
        assert store.get_active() == "/repo/a"


class TestJsonRepoStoreSave:
    def test_save_creates_directory_and_file(self, store, store_path):
        store.load()
        store.add_open("/repo/a")
        store.save()
        assert store_path.exists()
        data = json.loads(store_path.read_text())
        assert data["open"] == ["/repo/a"]
        assert data["active"] == "/repo/a"


class TestJsonRepoStoreAddOpen:
    def test_add_open_sets_active(self, store):
        store.load()
        store.add_open("/repo/a")
        assert store.get_open_repos() == ["/repo/a"]
        assert store.get_active() == "/repo/a"

    def test_add_open_removes_from_recent(self, store, store_path):
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps({
            "open": [], "recent": ["/repo/a", "/repo/b"], "active": None,
        }))
        store.load()
        store.add_open("/repo/a")
        assert "/repo/a" not in store.get_recent_repos()
        assert store.get_open_repos() == ["/repo/a"]

    def test_add_open_no_duplicate(self, store):
        store.load()
        store.add_open("/repo/a")
        store.add_open("/repo/a")
        assert store.get_open_repos() == ["/repo/a"]


class TestJsonRepoStoreCloseRepo:
    def test_close_moves_to_recent_head(self, store):
        store.load()
        store.add_open("/repo/a")
        store.add_open("/repo/b")
        store.close_repo("/repo/a")
        assert store.get_open_repos() == ["/repo/b"]
        assert store.get_recent_repos()[0] == "/repo/a"

    def test_close_active_clears_active(self, store):
        store.load()
        store.add_open("/repo/a")
        store.close_repo("/repo/a")
        assert store.get_active() is None


class TestJsonRepoStoreRecentLimit:
    def test_recent_capped_at_20(self, store):
        store.load()
        for i in range(25):
            store.add_open(f"/repo/{i}")
        for i in range(25):
            store.close_repo(f"/repo/{i}")
        assert len(store.get_recent_repos()) == 20

    def test_recent_excludes_open_repos(self, store, store_path):
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps({
            "open": ["/repo/a"],
            "recent": ["/repo/a", "/repo/b"],
            "active": "/repo/a",
        }))
        store.load()
        assert "/repo/a" not in store.get_recent_repos()
        assert store.get_recent_repos() == ["/repo/b"]


class TestJsonRepoStoreRemoveRecent:
    def test_remove_recent(self, store):
        store.load()
        store.add_open("/repo/a")
        store.close_repo("/repo/a")
        assert "/repo/a" in store.get_recent_repos()
        store.remove_recent("/repo/a")
        assert "/repo/a" not in store.get_recent_repos()


class TestJsonRepoStoreSetActive:
    def test_set_active(self, store):
        store.load()
        store.add_open("/repo/a")
        store.add_open("/repo/b")
        store.set_active("/repo/a")
        assert store.get_active() == "/repo/a"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_repo_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'git_gui.infrastructure.repo_store'`

- [ ] **Step 3: Implement JsonRepoStore**

Create `git_gui/infrastructure/repo_store.py`:

```python
from __future__ import annotations
import json
from pathlib import Path

_RECENT_LIMIT = 20


class JsonRepoStore:
    """Persists open/recent repo lists to a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path.home() / ".gitstack" / "repos.json"
        self._open: list[str] = []
        self._recent: list[str] = []
        self._active: str | None = None

    def load(self) -> None:
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._open = list(data.get("open", []))
            self._recent = list(data.get("recent", []))
            self._active = data.get("active")
        else:
            self._open = []
            self._recent = []
            self._active = None

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"open": self._open, "recent": self._recent, "active": self._active}
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_open_repos(self) -> list[str]:
        return list(self._open)

    def get_recent_repos(self) -> list[str]:
        return [r for r in self._recent if r not in self._open]

    def get_active(self) -> str | None:
        return self._active

    def add_open(self, path: str) -> None:
        if path not in self._open:
            self._open.append(path)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_repo_store.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/repo_store.py tests/infrastructure/test_repo_store.py
git commit -m "feat: add JsonRepoStore with full test coverage"
```

---

### Task 3: Add set_buses() to Existing Widgets

**Files:**
- Modify: `git_gui/presentation/widgets/sidebar.py`
- Modify: `git_gui/presentation/widgets/graph.py`
- Modify: `git_gui/presentation/widgets/diff.py`
- Modify: `git_gui/presentation/widgets/working_tree.py`
- Modify: `git_gui/presentation/widgets/hunk_diff.py`

Each widget that holds `self._queries` and/or `self._commands` needs a `set_buses()` method so MainWindow can hot-swap the repo. When `None` is passed, the widget enters an empty state.

- [ ] **Step 1: Add set_buses() + clear() to SidebarWidget**

In `git_gui/presentation/widgets/sidebar.py`, add after the `reload()` method:

```python
    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._commands = commands
        if queries is None:
            self._model.clear()
        else:
            self.reload()
```

- [ ] **Step 2: Add set_buses() to GraphWidget**

In `git_gui/presentation/widgets/graph.py`, add after the `reload()` method:

```python
    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        if queries is None:
            self._model.reload([], {})
        else:
            self.reload()
```

- [ ] **Step 3: Add set_buses() to DiffWidget**

In `git_gui/presentation/widgets/diff.py`, add after `__init__`:

```python
    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        if queries is None:
            self._current_oid = None
            self._detail.clear()
            self._msg_view.clear()
            self._diff_model.reload([])
            self._diff_view.clear()
```

Also add a `clear()` method to `CommitDetailWidget`. Read the file to check its current interface — it already exists at `git_gui/presentation/widgets/commit_detail.py`. Add if missing:

```python
    def clear(self) -> None:
        self._oid_label.clear()
        self._author_label.clear()
        self._date_label.clear()
        self._refs_label.clear()
```

- [ ] **Step 4: Add set_buses() to WorkingTreeWidget**

In `git_gui/presentation/widgets/working_tree.py`, add after `__init__`:

```python
    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._commands = commands
        self._file_model.set_commands(commands)
        self._hunk_diff.set_buses(queries, commands)
        if queries is None:
            self._file_model.reload([], set())
            self._hunk_diff.clear()
```

The `WorkingTreeModel` holds a reference to `commands` — add a setter. In `git_gui/presentation/widgets/working_tree_model.py`, add:

```python
    def set_commands(self, commands: CommandBus | None) -> None:
        self._commands = commands
```

- [ ] **Step 5: Add set_buses() to HunkDiffWidget**

In `git_gui/presentation/widgets/hunk_diff.py`, add after `__init__`:

```python
    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._commands = commands
        if queries is None:
            self.clear()
```

- [ ] **Step 6: Verify app still works**

Run: `uv run pytest -v`
Expected: All existing tests PASS (set_buses is additive, no existing behavior changed)

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/widgets/sidebar.py git_gui/presentation/widgets/graph.py git_gui/presentation/widgets/diff.py git_gui/presentation/widgets/working_tree.py git_gui/presentation/widgets/hunk_diff.py git_gui/presentation/widgets/working_tree_model.py git_gui/presentation/widgets/commit_detail.py
git commit -m "feat: add set_buses() to all widgets for repo hot-swap"
```

---

### Task 4: RepoListWidget

**Files:**
- Create: `git_gui/presentation/widgets/repo_list.py`

- [ ] **Step 1: Create RepoListWidget**

Create `git_gui/presentation/widgets/repo_list.py`:

```python
# git_gui/presentation/widgets/repo_list.py
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMenu, QPushButton,
    QTreeView, QVBoxLayout, QWidget,
)
from git_gui.domain.ports import IRepoStore


class RepoListWidget(QWidget):
    repo_switch_requested = Signal(str)
    repo_open_requested = Signal(str)
    repo_close_requested = Signal(str)
    repo_remove_recent_requested = Signal(str)

    def __init__(self, repo_store: IRepoStore, parent=None) -> None:
        super().__init__(parent)
        self._store = repo_store

        # Header with "+" button
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(4, 4, 4, 0)
        title = QLabel("REPOSITORIES")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() - 1)
        title.setFont(title_font)
        header_layout.addWidget(title, 1)

        self._btn_add = QPushButton("+")
        self._btn_add.setFixedSize(22, 22)
        self._btn_add.setToolTip("Open Repository...")
        self._btn_add.clicked.connect(self._on_add_clicked)
        header_layout.addWidget(self._btn_add)

        # Tree view
        self._tree = QTreeView()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.clicked.connect(self._on_item_clicked)

        self._model = QStandardItemModel()
        self._tree.setModel(self._model)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header_layout)
        layout.addWidget(self._tree)

    def reload(self) -> None:
        self._model.clear()
        active = self._store.get_active()

        # Open repos section
        open_repos = self._store.get_open_repos()
        if open_repos:
            open_header = QStandardItem("OPEN")
            open_header.setEditable(False)
            open_header.setSelectable(False)
            open_header.setData("header", Qt.UserRole + 1)
            for path in open_repos:
                item = self._make_repo_item(path, "open", is_active=(path == active))
                open_header.appendRow(item)
            self._model.appendRow(open_header)

        # Recent repos section
        recent_repos = self._store.get_recent_repos()
        if recent_repos:
            recent_header = QStandardItem("RECENT")
            recent_header.setEditable(False)
            recent_header.setSelectable(False)
            recent_header.setData("header", Qt.UserRole + 1)
            for path in recent_repos:
                item = self._make_repo_item(path, "recent", is_active=False)
                recent_header.appendRow(item)
            self._model.appendRow(recent_header)

        self._tree.expandAll()

    def _make_repo_item(self, path: str, kind: str, is_active: bool) -> QStandardItem:
        display_name = Path(path).name
        item = QStandardItem(display_name)
        item.setEditable(False)
        item.setToolTip(path)
        item.setData(path, Qt.UserRole)
        item.setData(kind, Qt.UserRole + 1)
        if is_active:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        return item

    def _on_item_clicked(self, index) -> None:
        kind = index.data(Qt.UserRole + 1)
        path = index.data(Qt.UserRole)
        if kind == "open" and path:
            self.repo_switch_requested.emit(path)
        elif kind == "recent" and path:
            self.repo_open_requested.emit(path)

    def _show_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        kind = index.data(Qt.UserRole + 1)
        path = index.data(Qt.UserRole)

        menu = QMenu(self)
        if kind == "open" and path:
            menu.addAction("Close").triggered.connect(
                lambda: self.repo_close_requested.emit(path))
        elif kind == "recent" and path:
            menu.addAction("Remove from recent").triggered.connect(
                lambda: self.repo_remove_recent_requested.emit(path))
        elif kind == "header":
            title = index.data(Qt.DisplayRole)
            if title == "OPEN":
                menu.addAction("Open Repository...").triggered.connect(self._on_add_clicked)
            else:
                return
        else:
            return
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _on_add_clicked(self) -> None:
        dialog = QFileDialog(self)
        dialog.setWindowTitle("Open Repository")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        if dialog.exec() == QFileDialog.Accepted:
            dirs = dialog.selectedFiles()
            if dirs:
                self.repo_open_requested.emit(dirs[0])
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/repo_list.py
git commit -m "feat: add RepoListWidget with open/recent sections"
```

---

### Task 5: MainWindow — Sidebar Split & Repo Switching

**Files:**
- Modify: `git_gui/presentation/main_window.py`

- [ ] **Step 1: Add imports and update constructor signature**

In `git_gui/presentation/main_window.py`, update the imports to add:

```python
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
)
```
(no change needed — QSplitter already imported)

Add new import:

```python
from git_gui.domain.ports import IRepoStore
from git_gui.infrastructure.pygit2_repo import Pygit2Repository
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.widgets.repo_list import RepoListWidget
```

Update `MainWindow.__init__` signature to accept `IRepoStore`:

```python
def __init__(self, queries: QueryBus | None, commands: CommandBus | None,
             repo_store: IRepoStore, repo_path: str | None = None, parent=None) -> None:
```

- [ ] **Step 2: Split sidebar with vertical QSplitter**

In `MainWindow.__init__`, replace the line that adds `self._sidebar` directly to the horizontal splitter. Instead:

```python
        self._repo_store = repo_store
        self._repo_list = RepoListWidget(repo_store)

        # Vertical splitter for sidebar: branches on top, repos on bottom
        sidebar_splitter = QSplitter(Qt.Vertical)
        sidebar_splitter.addWidget(self._sidebar)
        sidebar_splitter.addWidget(self._repo_list)
        sidebar_splitter.setSizes([400, 400])
```

Then in the horizontal splitter, replace `self._sidebar` with `sidebar_splitter`:

```python
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(sidebar_splitter)
        splitter.addWidget(self._graph)
        splitter.addWidget(self._right_stack)
        splitter.setSizes([220, 230, 950])
```

- [ ] **Step 3: Add _switch_repo() method**

Add after `_on_branch_changed`:

```python
    def _switch_repo(self, path: str) -> None:
        repo = Pygit2Repository(path)
        self._queries = QueryBus.from_reader(repo)
        self._commands = CommandBus.from_writer(repo)
        self._sidebar.set_buses(self._queries, self._commands)
        self._graph.set_buses(self._queries, self._commands)
        self._diff.set_buses(self._queries, self._commands)
        self._working_tree.set_buses(self._queries, self._commands)
        self._repo_store.set_active(path)
        self._repo_store.save()
        self._repo_list.reload()
        self.setWindowTitle(f"GitStack — {path}")
        self._right_stack.setCurrentIndex(0)

    def _enter_empty_state(self) -> None:
        self._queries = None
        self._commands = None
        self._sidebar.set_buses(None, None)
        self._graph.set_buses(None, None)
        self._diff.set_buses(None, None)
        self._working_tree.set_buses(None, None)
        self._repo_list.reload()
        self.setWindowTitle("GitStack")
```

- [ ] **Step 4: Wire RepoListWidget signals**

Add after existing signal wiring in `__init__`:

```python
        # Repo list signals
        self._repo_list.repo_switch_requested.connect(self._switch_repo)
        self._repo_list.repo_open_requested.connect(self._on_repo_open)
        self._repo_list.repo_close_requested.connect(self._on_repo_close)
        self._repo_list.repo_remove_recent_requested.connect(self._on_repo_remove_recent)
```

Add the handler methods:

```python
    def _on_repo_open(self, path: str) -> None:
        self._repo_store.add_open(path)
        self._repo_store.save()
        self._switch_repo(path)

    def _on_repo_close(self, path: str) -> None:
        self._repo_store.close_repo(path)
        self._repo_store.save()
        open_repos = self._repo_store.get_open_repos()
        if open_repos:
            self._switch_repo(open_repos[0])
        else:
            self._enter_empty_state()

    def _on_repo_remove_recent(self, path: str) -> None:
        self._repo_store.remove_recent(path)
        self._repo_store.save()
        self._repo_list.reload()
```

- [ ] **Step 5: Guard _reload against empty state**

Update `_reload` to handle `None` queries:

```python
    def _reload(self) -> None:
        if self._queries is None:
            return
        self._sidebar.reload()
        self._graph.reload()
```

Similarly guard `_get_current_branch`, `_on_push`, `_on_pull`:

```python
    def _get_current_branch(self) -> str | None:
        if self._queries is None:
            return None
        branches = self._queries.get_branches.execute()
        for b in branches:
            if b.is_head and not b.is_remote:
                return b.name
        return None
```

- [ ] **Step 6: Update initial load in __init__**

At the end of `__init__`, replace the bare `self._reload()` with:

```python
        if self._queries is not None:
            self._reload()
        self._repo_list.reload()
```

- [ ] **Step 7: Verify existing tests still pass**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/main_window.py
git commit -m "feat: split sidebar and add repo switching to MainWindow"
```

---

### Task 6: Startup Flow — main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Rewrite main.py**

Replace `main.py` contents with:

```python
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFileDialog
from git_gui.infrastructure.pygit2_repo import Pygit2Repository
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.main_window import MainWindow


def _pick_repo() -> str:
    dialog = QFileDialog()
    dialog.setWindowTitle("Open Repository")
    dialog.setFileMode(QFileDialog.Directory)
    dialog.setOption(QFileDialog.ShowDirsOnly, True)
    if dialog.exec() == QFileDialog.Accepted:
        dirs = dialog.selectedFiles()
        return dirs[0] if dirs else ""
    return ""


def _find_valid_repo(repo_store: JsonRepoStore) -> str | None:
    """Return the first valid repo path from active or open list, pruning invalid ones."""
    active = repo_store.get_active()
    if active and Path(active).is_dir():
        return active

    for path in list(repo_store.get_open_repos()):
        if Path(path).is_dir():
            repo_store.set_active(path)
            return path
        repo_store.close_repo(path)

    repo_store.save()
    return None


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("GitStack")

    repo_store = JsonRepoStore()
    repo_store.load()

    repo_path = _find_valid_repo(repo_store)

    if not repo_path:
        repo_path = _pick_repo()
        if not repo_path:
            sys.exit(0)
        repo_store.add_open(repo_path)
        repo_store.save()

    if repo_path not in repo_store.get_open_repos():
        repo_store.add_open(repo_path)
        repo_store.save()

    repo = Pygit2Repository(repo_path)
    queries = QueryBus.from_reader(repo)
    commands = CommandBus.from_writer(repo)

    window = MainWindow(queries, commands, repo_store, repo_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 3: Manual smoke test**

Run: `uv run python main.py`
Expected:
1. First launch (no `~/.gitstack/repos.json`): file dialog appears
2. Select a repo → app opens, repo appears in bottom-left "OPEN" section as bold
3. Click "+" → file dialog → select another repo → switches to it, both in OPEN list
4. Right-click an open repo → Close → repo moves to RECENT
5. Click a recent repo → opens it (moves back to OPEN)
6. Close app, relaunch → restores last active repo without dialog

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: update startup flow with repo store and auto-restore"
```
