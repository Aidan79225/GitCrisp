# Git GUI — Design Spec
_Date: 2026-04-03_

## Overview

A full-featured Git client built with Python (PySide6 + pygit2), modelled after GitAhead. Follows clean architecture with strict layer separation: domain → application → infrastructure → presentation.

---

## Layout

Three-panel horizontal layout:

- **Left:** `SidebarWidget` — local branches, remote branches, tags, stashes
- **Center:** `GraphWidget` — commit graph with "Uncommitted Changes" as a synthetic top entry when working tree is dirty
- **Right:** `DiffWidget` — file list (top half) + diff viewer (bottom half)

Cross-widget communication via Qt signals through `MainWindow`. No widget holds a direct reference to another.

---

## Layer Structure

```
git_gui/
├── domain/
│   ├── entities.py      # Commit, Branch, Remote, FileStatus, Hunk (dataclasses)
│   └── ports.py         # IRepositoryReader, IRepositoryWriter (Protocol)
│
├── application/
│   ├── queries.py       # GetCommitGraph, GetBranches, GetFileDiff, GetWorkingTree
│   └── commands.py      # StageFiles, CreateCommit, Checkout, CreateBranch,
│                        # DeleteBranch, Merge, Rebase, Push, Pull, Fetch, Stash, PopStash
│
├── infrastructure/
│   └── pygit2_repo.py   # Pygit2Repository implements IRepositoryReader + IRepositoryWriter
│
└── presentation/
    ├── main_window.py
    ├── widgets/
    │   ├── sidebar.py
    │   ├── graph.py
    │   └── diff.py
    └── models/
        ├── graph_model.py   # QAbstractTableModel for commit graph
        └── diff_model.py    # QAbstractListModel for file status list
```

---

## Domain

### Entities (`domain/entities.py`)

```python
@dataclass
class Commit:
    oid: str
    message: str
    author: str
    timestamp: datetime
    parents: list[str]

@dataclass
class Branch:
    name: str
    is_remote: bool
    is_head: bool
    target_oid: str

@dataclass
class FileStatus:
    path: str
    status: Literal["staged", "unstaged", "untracked", "conflicted"]
    delta: Literal["added", "modified", "deleted", "renamed"]

@dataclass
class Hunk:
    header: str
    lines: list[tuple[Literal["+", "-", " "], str]]
```

### Ports (`domain/ports.py`)

```python
class IRepositoryReader(Protocol):
    def get_commits(self, limit: int) -> list[Commit]: ...
    def get_branches(self) -> list[Branch]: ...
    def get_file_diff(self, oid: str, path: str) -> list[Hunk]: ...
    def get_working_tree(self) -> list[FileStatus]: ...

class IRepositoryWriter(Protocol):
    def stage(self, paths: list[str]) -> None: ...
    def unstage(self, paths: list[str]) -> None: ...
    def commit(self, message: str) -> Commit: ...
    def checkout(self, branch: str) -> None: ...
    def create_branch(self, name: str, from_oid: str) -> Branch: ...
    def delete_branch(self, name: str) -> None: ...
    def merge(self, branch: str) -> None: ...
    def rebase(self, branch: str) -> None: ...
    def push(self, remote: str, branch: str) -> None: ...
    def pull(self, remote: str, branch: str) -> None: ...
    def fetch(self, remote: str) -> None: ...
    def stash(self, message: str) -> None: ...
    def pop_stash(self, index: int) -> None: ...
```

---

## Application

### Queries (`application/queries.py`)

One class per read operation. Each takes an `IRepositoryReader` at construction.

- `GetCommitGraph(reader).execute(limit=1000) -> list[Commit]`
- `GetBranches(reader).execute() -> list[Branch]`
- `GetFileDiff(reader).execute(oid, path) -> list[Hunk]`
- `GetWorkingTree(reader).execute() -> list[FileStatus]`

### Commands (`application/commands.py`)

One class per write operation. Each takes an `IRepositoryWriter` at construction.

- `StageFiles`, `UnstageFiles`, `CreateCommit`
- `Checkout`, `CreateBranch`, `DeleteBranch`
- `Merge`, `Rebase`
- `Push`, `Pull`, `Fetch`
- `Stash`, `PopStash`

---

## Infrastructure

### `Pygit2Repository` (`infrastructure/pygit2_repo.py`)

Implements both `IRepositoryReader` and `IRepositoryWriter` using pygit2.

Key implementation notes:
- `get_commits`: walk with `GIT_SORT_TOPOLOGICAL | GIT_SORT_TIME`
- `get_file_diff`: use a sentinel `WORKING_TREE_OID` constant to distinguish working tree diffs from commit diffs
- `push/pull/fetch`: require a `CredentialsProvider` port (swappable: SSH agent, keychain, prompt dialog) to handle auth

---

## Presentation

### `MainWindow` (`presentation/main_window.py`)

Builds the adapter, instantiates all use cases, constructs the three-panel splitter, and wires signals between widgets.

```python
repo = Pygit2Repository(repo_path)
queries = QueryBus(repo)    # holds all query use case instances
commands = CommandBus(repo) # holds all command use case instances

splitter = QSplitter(Qt.Horizontal)
splitter.addWidget(SidebarWidget(queries, commands))
splitter.addWidget(GraphWidget(queries, commands))
splitter.addWidget(DiffWidget(queries, commands))
```

### `GraphWidget` (`presentation/widgets/graph.py`)

- Backed by `GraphModel(QAbstractTableModel)` — one row per commit
- Columns: graph lanes, refs/tags, message, author, date
- Synthetic "Uncommitted Changes" row at top when working tree is dirty
- Emits `commit_selected = Signal(str)` (oid) on row selection

### `DiffWidget` (`presentation/widgets/diff.py`)

- Top half: `QListView` of `FileStatus` items (staged/unstaged sections)
- Bottom half: diff renderer using `QPlainTextEdit` with line-level syntax highlighting (`+` green, `-` red)
- Responds to `commit_selected` signal — loads commit diff or working tree diff accordingly

### `SidebarWidget` (`presentation/widgets/sidebar.py`)

- `QTreeView` with collapsible sections: LOCAL BRANCHES, REMOTE BRANCHES, TAGS, STASHES
- Double-click branch → `Checkout` command
- Right-click context menu → merge, rebase, delete, push

---

## Credentials

Auth for push/pull/fetch is handled via a `CredentialsProvider` port injected into the infrastructure layer. Initial implementation: SSH agent passthrough. Future: HTTPS token prompt dialog.

---

## Entry Point

`main.py` opens a `QFileDialog` to select a repository path, then constructs and shows `MainWindow`.
