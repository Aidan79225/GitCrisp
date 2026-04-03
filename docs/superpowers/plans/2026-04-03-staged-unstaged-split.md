# Staged/Unstaged Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When "Uncommitted Changes" is selected, split DiffWidget into a sectioned file list (STAGED/UNSTAGED) and two diff editors showing staged and unstaged changes simultaneously.

**Architecture:** Add `get_staged_diff` through all layers (port → infrastructure → use case → bus), then extend `DiffWidget` with a `QStackedWidget` that switches between the existing commit-mode layout and a new working-tree-mode layout with `QTreeView` sections and two diff editors.

**Tech Stack:** Python 3.13, PySide6 6.11, pygit2 1.19, pytest, pytest-qt

---

## File Map

| File | Change |
|------|--------|
| `git_gui/domain/ports.py` | Add `get_staged_diff(path)` to `IRepositoryReader` |
| `git_gui/infrastructure/pygit2_repo.py` | Implement `get_staged_diff` (index vs HEAD) |
| `git_gui/application/queries.py` | Add `GetStagedDiff` class |
| `git_gui/presentation/bus.py` | Add `get_staged_diff` field + wire in `from_reader` |
| `git_gui/presentation/widgets/diff.py` | Add working tree mode via `QStackedWidget` |
| `tests/infrastructure/test_reads.py` | Add `get_staged_diff` tests |
| `tests/application/test_queries.py` | Add `GetStagedDiff` test |

---

## Task 1: `get_staged_diff` — port, infrastructure, query, bus

**Files:**
- Modify: `git_gui/domain/ports.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`
- Modify: `git_gui/application/queries.py`
- Modify: `git_gui/presentation/bus.py`
- Modify: `tests/infrastructure/test_reads.py`
- Modify: `tests/application/test_queries.py`

- [ ] **Step 1: Write the failing infrastructure tests**

Add to `tests/infrastructure/test_reads.py`:

```python
def test_get_staged_diff_empty_when_nothing_staged(repo_impl):
    hunks = repo_impl.get_staged_diff("README.md")
    assert hunks == []


def test_get_staged_diff_returns_hunks_after_staging(repo_path, repo_impl):
    (repo_path / "README.md").write_text("# Test Repo\nnew line\n")
    repo_impl.stage(["README.md"])
    hunks = repo_impl.get_staged_diff("README.md")
    assert len(hunks) >= 1
    all_lines = [line for h in hunks for line in h.lines]
    added_lines = [content for origin, content in all_lines if origin == "+"]
    assert any("new line" in line for line in added_lines)


def test_get_staged_diff_new_file_unborn_head(tmp_path):
    """get_staged_diff on a brand-new repo (no commits yet) shows staged new file."""
    import pygit2
    from git_gui.infrastructure.pygit2_repo import Pygit2Repository
    repo = pygit2.init_repository(str(tmp_path))
    (tmp_path / "new.txt").write_text("hello\n")
    repo.index.add("new.txt")
    repo.index.write()
    impl = Pygit2Repository(str(tmp_path))
    hunks = impl.get_staged_diff("new.txt")
    assert len(hunks) >= 1
    all_lines = [line for h in hunks for line in h.lines]
    added_lines = [content for origin, content in all_lines if origin == "+"]
    assert any("hello" in line for line in added_lines)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/infrastructure/test_reads.py::test_get_staged_diff_empty_when_nothing_staged tests/infrastructure/test_reads.py::test_get_staged_diff_returns_hunks_after_staging tests/infrastructure/test_reads.py::test_get_staged_diff_new_file_unborn_head -v
```

Expected: `AttributeError: 'Pygit2Repository' object has no attribute 'get_staged_diff'`

- [ ] **Step 3: Add `get_staged_diff` to `IRepositoryReader` in `domain/ports.py`**

Add one line to `IRepositoryReader`, after `get_file_diff`:

```python
    def get_staged_diff(self, path: str) -> list[Hunk]: ...
```

Full updated `IRepositoryReader`:

```python
@runtime_checkable
class IRepositoryReader(Protocol):
    def get_commits(self, limit: int) -> list[Commit]: ...
    def get_branches(self) -> list[Branch]: ...
    def get_stashes(self) -> list[Stash]: ...
    def get_commit_files(self, oid: str) -> list[FileStatus]: ...
    def get_file_diff(self, oid: str, path: str) -> list[Hunk]: ...
    def get_staged_diff(self, path: str) -> list[Hunk]: ...
    def get_working_tree(self) -> list[FileStatus]: ...
```

- [ ] **Step 4: Implement `get_staged_diff` in `infrastructure/pygit2_repo.py`**

Add this method in the reads section (after `get_file_diff`, before `get_working_tree`):

```python
    def get_staged_diff(self, path: str) -> list[Hunk]:
        # Diff the index against HEAD tree to show what is staged for commit.
        # For unborn HEAD (no commits yet), diff against an empty tree.
        if self._repo.head_is_unborn:
            empty_tree_oid = self._repo.TreeBuilder().write()
            empty_tree = self._repo.get(empty_tree_oid)
            diff = self._repo.index.diff_to_tree(empty_tree)
        else:
            head_commit = self._repo.head.peel(pygit2.Commit)
            diff = self._repo.index.diff_to_tree(head_commit.tree)
        for patch in diff:
            if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                return _diff_to_hunks(patch)
        return []
```

- [ ] **Step 5: Run infrastructure tests to confirm they pass**

```bash
uv run pytest tests/infrastructure/test_reads.py -v
```

Expected: all 14 tests PASS.

- [ ] **Step 6: Write the failing application test**

Add to `tests/application/test_queries.py`:

```python
def test_get_staged_diff_delegates_to_reader():
    reader = _reader()
    reader.get_staged_diff.return_value = [Hunk("@@ -1,1 +1,2 @@", [("+", "line\n")])]
    from git_gui.application.queries import GetStagedDiff
    result = GetStagedDiff(reader).execute("a.py")
    reader.get_staged_diff.assert_called_once_with("a.py")
    assert len(result) == 1
```

- [ ] **Step 7: Run to confirm it fails**

```bash
uv run pytest tests/application/test_queries.py::test_get_staged_diff_delegates_to_reader -v
```

Expected: `ImportError` — `GetStagedDiff` not defined.

- [ ] **Step 8: Add `GetStagedDiff` to `application/queries.py`**

Append to `git_gui/application/queries.py`:

```python
class GetStagedDiff:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, path: str) -> list[Hunk]:
        return self._reader.get_staged_diff(path)
```

- [ ] **Step 9: Update `presentation/bus.py` to include `GetStagedDiff`**

Replace the entire file:

```python
# git_gui/presentation/bus.py
from __future__ import annotations
from dataclasses import dataclass
from git_gui.domain.ports import IRepositoryReader, IRepositoryWriter
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
)
from git_gui.application.commands import (
    StageFiles, UnstageFiles, CreateCommit,
    Checkout, CreateBranch, DeleteBranch,
    Merge, Rebase, Push, Pull, Fetch,
    Stash, PopStash,
)


@dataclass
class QueryBus:
    get_commit_graph: GetCommitGraph
    get_branches: GetBranches
    get_stashes: GetStashes
    get_commit_files: GetCommitFiles
    get_file_diff: GetFileDiff
    get_staged_diff: GetStagedDiff
    get_working_tree: GetWorkingTree

    @classmethod
    def from_reader(cls, reader: IRepositoryReader) -> "QueryBus":
        return cls(
            get_commit_graph=GetCommitGraph(reader),
            get_branches=GetBranches(reader),
            get_stashes=GetStashes(reader),
            get_commit_files=GetCommitFiles(reader),
            get_file_diff=GetFileDiff(reader),
            get_staged_diff=GetStagedDiff(reader),
            get_working_tree=GetWorkingTree(reader),
        )


@dataclass
class CommandBus:
    stage_files: StageFiles
    unstage_files: UnstageFiles
    create_commit: CreateCommit
    checkout: Checkout
    create_branch: CreateBranch
    delete_branch: DeleteBranch
    merge: Merge
    rebase: Rebase
    push: Push
    pull: Pull
    fetch: Fetch
    stash: Stash
    pop_stash: PopStash

    @classmethod
    def from_writer(cls, writer: IRepositoryWriter) -> "CommandBus":
        return cls(
            stage_files=StageFiles(writer),
            unstage_files=UnstageFiles(writer),
            create_commit=CreateCommit(writer),
            checkout=Checkout(writer),
            create_branch=CreateBranch(writer),
            delete_branch=DeleteBranch(writer),
            merge=Merge(writer),
            rebase=Rebase(writer),
            push=Push(writer),
            pull=Pull(writer),
            fetch=Fetch(writer),
            stash=Stash(writer),
            pop_stash=PopStash(writer),
        )
```

- [ ] **Step 10: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all 60 tests PASS (59 existing + 4 new).

- [ ] **Step 11: Commit**

```bash
git add git_gui/domain/ports.py \
        git_gui/infrastructure/pygit2_repo.py \
        git_gui/application/queries.py \
        git_gui/presentation/bus.py \
        tests/infrastructure/test_reads.py \
        tests/application/test_queries.py
git commit -m "feat: add get_staged_diff through domain, infrastructure, query, and bus"
```

---

## Task 2: DiffWidget — working tree mode

**Files:**
- Modify: `git_gui/presentation/widgets/diff.py`

No new test file needed — the working tree mode is a UI-only change. The underlying queries are already tested. Run the existing suite after to confirm no regressions.

- [ ] **Step 1: Replace `diff.py` with the new implementation**

```python
# git_gui/presentation/widgets/diff.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor, QStandardItem, QStandardItemModel,
    QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QLabel, QListView, QPlainTextEdit, QSplitter, QStackedWidget,
    QTreeView, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.diff_model import DiffModel


class DiffWidget(QWidget):
    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._current_oid: str | None = None

        # ── commit mode (stack page 0) ──────────────────────────────────────
        self._commit_file_view = QListView()
        self._commit_file_view.setEditTriggers(QListView.NoEditTriggers)
        self._commit_diff_view = self._make_diff_editor()
        self._commit_diff_model = DiffModel([])
        self._commit_file_view.setModel(self._commit_diff_model)
        self._commit_file_view.selectionModel().currentChanged.connect(
            self._on_commit_file_selected
        )

        commit_splitter = QSplitter(Qt.Vertical)
        commit_splitter.addWidget(self._commit_file_view)
        commit_splitter.addWidget(self._commit_diff_view)
        commit_splitter.setSizes([200, 400])

        commit_page = QWidget()
        commit_layout = QVBoxLayout(commit_page)
        commit_layout.setContentsMargins(0, 0, 0, 0)
        commit_layout.addWidget(commit_splitter)

        # ── working tree mode (stack page 1) ────────────────────────────────
        self._wt_tree = QTreeView()
        self._wt_tree.setHeaderHidden(True)
        self._wt_tree.setEditTriggers(QTreeView.NoEditTriggers)
        self._wt_model = QStandardItemModel()
        self._wt_tree.setModel(self._wt_model)
        self._wt_tree.selectionModel().currentChanged.connect(self._on_wt_file_selected)

        staged_label = QLabel("Staged Changes")
        self._staged_diff_view = self._make_diff_editor()
        unstaged_label = QLabel("Unstaged Changes")
        self._unstaged_diff_view = self._make_diff_editor()

        staged_container = QWidget()
        staged_layout = QVBoxLayout(staged_container)
        staged_layout.setContentsMargins(4, 4, 4, 0)
        staged_layout.addWidget(staged_label)
        staged_layout.addWidget(self._staged_diff_view)

        unstaged_container = QWidget()
        unstaged_layout = QVBoxLayout(unstaged_container)
        unstaged_layout.setContentsMargins(4, 4, 4, 0)
        unstaged_layout.addWidget(unstaged_label)
        unstaged_layout.addWidget(self._unstaged_diff_view)

        diff_splitter = QSplitter(Qt.Vertical)
        diff_splitter.addWidget(staged_container)
        diff_splitter.addWidget(unstaged_container)
        diff_splitter.setSizes([300, 300])

        wt_splitter = QSplitter(Qt.Horizontal)
        wt_splitter.addWidget(self._wt_tree)
        wt_splitter.addWidget(diff_splitter)
        wt_splitter.setSizes([200, 600])

        wt_page = QWidget()
        wt_layout = QVBoxLayout(wt_page)
        wt_layout.setContentsMargins(0, 0, 0, 0)
        wt_layout.addWidget(wt_splitter)

        # ── stack ────────────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.addWidget(commit_page)   # index 0: commit mode
        self._stack.addWidget(wt_page)       # index 1: working tree mode

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

    # ── public ───────────────────────────────────────────────────────────────

    def load_commit(self, oid: str) -> None:
        self._current_oid = oid
        if oid == WORKING_TREE_OID:
            self._stack.setCurrentIndex(1)
            self._load_working_tree()
        else:
            self._stack.setCurrentIndex(0)
            files = self._queries.get_commit_files.execute(oid)
            self._commit_diff_model.reload(files)
            self._commit_diff_view.clear()
            if files:
                self._commit_file_view.setCurrentIndex(self._commit_diff_model.index(0))

    # ── private ──────────────────────────────────────────────────────────────

    def _make_diff_editor(self) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = editor.font()
        font.setFamily("Courier New")
        editor.setFont(font)
        return editor

    def _load_working_tree(self) -> None:
        self._wt_model.clear()
        files = self._queries.get_working_tree.execute()
        staged = [f for f in files if f.status == "staged"]
        unstaged = [f for f in files if f.status in ("unstaged", "untracked", "conflicted")]

        for title, section_files in [("STAGED", staged), ("UNSTAGED", unstaged)]:
            header = QStandardItem(title)
            header.setEditable(False)
            header.setSelectable(False)
            for f in section_files:
                item = QStandardItem(f.path)
                item.setEditable(False)
                item.setData(f, Qt.UserRole)
                header.appendRow(item)
            self._wt_model.appendRow(header)

        self._wt_tree.expandAll()
        self._staged_diff_view.clear()
        self._unstaged_diff_view.clear()

    def _on_commit_file_selected(self, index) -> None:
        if not index.isValid() or self._current_oid is None:
            return
        file_status = self._commit_diff_model.data(index, Qt.UserRole)
        if file_status is None:
            return
        hunks = self._queries.get_file_diff.execute(self._current_oid, file_status.path)
        self._render_diff(self._commit_diff_view, hunks)

    def _on_wt_file_selected(self, index) -> None:
        if not index.isValid():
            return
        file_status = index.data(Qt.UserRole)
        if file_status is None:
            return  # section header clicked — nothing to show
        path = file_status.path
        self._render_diff(
            self._staged_diff_view,
            self._queries.get_staged_diff.execute(path),
        )
        self._render_diff(
            self._unstaged_diff_view,
            self._queries.get_file_diff.execute(WORKING_TREE_OID, path),
        )

    def _render_diff(self, editor: QPlainTextEdit, hunks) -> None:
        editor.clear()
        cursor = editor.textCursor()
        added_fmt = QTextCharFormat()
        added_fmt.setForeground(QColor("#2ea043"))
        removed_fmt = QTextCharFormat()
        removed_fmt.setForeground(QColor("#f85149"))
        header_fmt = QTextCharFormat()
        header_fmt.setForeground(QColor("#58a6ff"))
        default_fmt = QTextCharFormat()

        for hunk in hunks:
            cursor.setCharFormat(header_fmt)
            cursor.insertText(hunk.header + "\n")
            for origin, content in hunk.lines:
                if origin == "+":
                    cursor.setCharFormat(added_fmt)
                elif origin == "-":
                    cursor.setCharFormat(removed_fmt)
                else:
                    cursor.setCharFormat(default_fmt)
                cursor.insertText(content if content.endswith("\n") else content + "\n")

        editor.setTextCursor(cursor)
```

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all 63 tests PASS (60 from Task 1 + 3 new infrastructure tests).

Wait — Task 1 adds 4 tests (3 infra + 1 application). So the total after both tasks is 63.

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/diff.py
git commit -m "feat: split DiffWidget into staged/unstaged sections for working tree mode"
```

---

## Self-Review

**Spec coverage:**
- ✅ `QStackedWidget` with commit mode (page 0) and working tree mode (page 1)
- ✅ `QTreeView` with STAGED/UNSTAGED non-selectable headers in working tree mode
- ✅ Two `QPlainTextEdit` diff editors with labels in working tree mode
- ✅ Clicking a file shows staged diff (top) and unstaged diff (bottom)
- ✅ Empty sections still show their header
- ✅ `get_staged_diff` added through all layers
- ✅ Commit mode unchanged

**Placeholder scan:** None found.

**Type consistency:** `get_staged_diff(path: str) -> list[Hunk]` is consistent across port, infrastructure, use case, and bus.
