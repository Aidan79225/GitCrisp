# Sidebar Repo Switcher Design

## Overview

Split the left sidebar into two halves using a vertical QSplitter. The top half retains the existing branch/stash tree. The bottom half adds a new repo list with two sections: **Open Repos** (persistent, like browser tabs) and **Recent Repos** (LRU history). Users can switch repos in-place within a single MainWindow.

## Architecture

### Domain Layer — IRepoStore Protocol

Add `IRepoStore` protocol to `git_gui/domain/ports.py`:

```python
class IRepoStore(Protocol):
    def load(self) -> None: ...
    def save(self) -> None: ...
    def get_open_repos(self) -> list[str]: ...
    def get_recent_repos(self) -> list[str]: ...  # excludes repos in open list
    def get_active(self) -> str | None: ...
    def add_open(self, path: str) -> None: ...     # adds to open, removes from recent, sets active
    def close_repo(self, path: str) -> None: ...   # removes from open, adds to recent head
    def remove_recent(self, path: str) -> None: ...
    def set_active(self, path: str) -> None: ...
```

### Infrastructure Layer — JsonRepoStore

New file: `git_gui/infrastructure/repo_store.py`

- Implements `IRepoStore`
- Storage location: `~/.gitstack/repos.json`
- JSON structure:
  ```json
  {
    "open": ["/path/to/repo1", "/path/to/repo2"],
    "recent": ["/path/to/repo3", "/path/to/repo4"],
    "active": "/path/to/repo1"
  }
  ```
- Recent list capped at 20 entries (LRU eviction — oldest removed first)
- Creates `~/.gitstack/` directory if it doesn't exist
- Returns empty state if file doesn't exist

### Presentation Layer — RepoListWidget

New file: `git_gui/presentation/widgets/repo_list.py`

**Structure:**
- QWidget containing a QTreeView + QStandardItemModel
- Two sections: OPEN REPOS, RECENT REPOS

**Display:**
- Each item shows the repo folder name (e.g., `GitStack`)
- Tooltip shows full path
- Active repo is bold/highlighted

**OPEN REPOS section header:**
- "+" QPushButton next to the title — opens file dialog
- Right-click on header — context menu with "Open Repository..."

**Interactions:**
- Single-click open repo → `repo_switch_requested(path)` signal
- Single-click recent repo → `repo_open_requested(path)` signal
- Right-click open repo → context menu: "Close" → `repo_close_requested(path)` signal
- Right-click recent repo → context menu: "Remove from recent" → `repo_remove_recent_requested(path)` signal
- "+" button / right-click header "Open Repository..." → file dialog → `repo_open_requested(path)` signal

**reload():** Reads from IRepoStore and refreshes the list.

### MainWindow Changes

**Sidebar split:**
- Replace direct `SidebarWidget` with a `QSplitter(Qt.Vertical)` containing:
  - Top: existing `SidebarWidget` (branches/stashes)
  - Bottom: new `RepoListWidget`
- Initial ratio: 1:1

**Repo switching — `_switch_repo(path: str)`:**
1. Create new `Pygit2Repository(path)`
2. Rebuild `QueryBus` and `CommandBus`
3. Inject new buses into all widgets via `set_buses(queries, commands)` method (new method on each widget)
4. Update `RepoStore` (set_active + save)
5. Call `_reload()` to refresh all widgets
6. Update window title to `"GitStack — {path}"`

**Signal wiring:**
- `repo_switch_requested(path)` → `_switch_repo(path)`
- `repo_open_requested(path)` → `repo_store.add_open(path)` + `_switch_repo(path)` + `repo_list.reload()`
- `repo_close_requested(path)` → `repo_store.close_repo(path)` + switch to next open repo or enter empty state + `repo_list.reload()`
- `repo_remove_recent_requested(path)` → `repo_store.remove_recent(path)` + `repo_list.reload()`

### Startup Flow (main.py)

1. Remove CLI argument handling (`sys.argv[1]`)
2. Create `QApplication`
3. Create `JsonRepoStore`, call `load()`
4. Determine initial repo:
   - Has `active` → use it
   - No active but open list non-empty → use first in open list
   - No open repos → show file dialog; user cancels → `sys.exit(0)`
5. Validate path exists; if not, remove from open list and try next. All invalid → file dialog.
6. Create `Pygit2Repository` + buses
7. Pass `RepoStore` instance into `MainWindow`
8. Show window

### Empty State

When all open repos are closed:
- Graph, Diff, WorkingTree, Sidebar (branches): cleared, showing no data
- Each widget's `set_buses()` accepts `None` to enter empty state
- RepoListWidget remains functional (recent list, "+" button)
- Window title: `"GitStack"`

## Files Changed

| File | Change |
|------|--------|
| `git_gui/domain/ports.py` | Add `IRepoStore` protocol |
| `git_gui/infrastructure/repo_store.py` | New — `JsonRepoStore` implementation |
| `git_gui/presentation/widgets/repo_list.py` | New — `RepoListWidget` |
| `git_gui/presentation/main_window.py` | Sidebar split, repo switching logic, signal wiring |
| `git_gui/presentation/widgets/sidebar.py` | Add `set_buses()` method |
| `git_gui/presentation/widgets/graph.py` | Add `set_buses()` method |
| `git_gui/presentation/widgets/diff.py` | Add `set_buses()` method |
| `git_gui/presentation/widgets/working_tree.py` | Add `set_buses()` method |
| `main.py` | New startup flow, remove CLI arg, integrate RepoStore |

## Constraints

- Dependency direction: Presentation → Domain ← Infrastructure
- RepoStore is app-level config, not git operation — lives in infrastructure but behind domain protocol
- No QSettings — plain JSON file
- Recent list max 20, LRU eviction
- Recent list excludes repos already in open list
