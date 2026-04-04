# Working Tree Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the working tree page with a 3-row layout: commit toolbar, file list with per-file staging checkboxes, and hunk diff with per-hunk staging checkboxes.

**Architecture:** Add `stage_hunk`/`unstage_hunk` to domain ports and implement via `git apply --cached`. Extract working tree UI from `DiffWidget` into a new `WorkingTreeWidget` with `WorkingTreeModel` and `HunkDiffWidget`. Move the stack switching to `MainWindow`.

**Tech Stack:** Python 3.13, PySide6 6.11, pygit2, pytest, pytest-qt

---

## File Map

| File | Change |
|------|--------|
| `git_gui/domain/ports.py` | Add `stage_hunk`, `unstage_hunk` to `IRepositoryWriter` |
| `git_gui/infrastructure/pygit2_repo.py` | Implement `stage_hunk`, `unstage_hunk` |
| `git_gui/application/commands.py` | Add `StageHunk`, `UnstageHunk` classes |
| `git_gui/presentation/bus.py` | Wire `stage_hunk`, `unstage_hunk` on `CommandBus` |
| `git_gui/presentation/widgets/working_tree_model.py` | New — file list model with checkboxes |
| `git_gui/presentation/widgets/hunk_diff.py` | New — scrollable hunk diff with per-hunk checkboxes |
| `git_gui/presentation/widgets/working_tree.py` | New — 3-row working tree widget |
| `git_gui/presentation/widgets/diff.py` | Remove working tree code, commit mode only |
| `git_gui/presentation/main_window.py` | Stack switching DiffWidget/WorkingTreeWidget |
| `tests/infrastructure/test_hunk_staging.py` | New — tests for stage_hunk/unstage_hunk |
| `tests/presentation/test_working_tree_model.py` | New — tests for WorkingTreeModel |

---

## Task 1: Domain & Infrastructure — hunk-level staging

**Files:**
- Modify: `git_gui/domain/ports.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`
- Create: `tests/infrastructure/test_hunk_staging.py`

**Context:** Add `stage_hunk(path, hunk_header)` and `unstage_hunk(path, hunk_header)` to the writer protocol. Implement in `Pygit2Repository` by building a minimal patch and applying via `git apply --cached`. The hunk header (e.g. `@@ -10,6 +10,8 @@ def foo():`) uniquely identifies a hunk within a file's diff.

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_hunk_staging.py`:

```python
import pygit2
import pytest
from pathlib import Path
from git_gui.infrastructure.pygit2_repo import Pygit2Repository


@pytest.fixture
def multi_hunk_repo(repo_path) -> tuple[Pygit2Repository, Path]:
    """Create a repo with a file that has two separate unstaged hunks."""
    impl = Pygit2Repository(str(repo_path))
    # Write a file with several lines, commit it
    lines = [f"line {i}\n" for i in range(1, 21)]
    (repo_path / "multi.txt").write_text("".join(lines))
    impl.stage(["multi.txt"])
    impl.commit("add multi.txt")

    # Modify two separate regions to create two hunks
    lines[1] = "CHANGED line 2\n"    # near top
    lines[17] = "CHANGED line 18\n"  # near bottom
    (repo_path / "multi.txt").write_text("".join(lines))
    return impl, repo_path


def test_stage_hunk_stages_only_one_hunk(multi_hunk_repo):
    impl, path = multi_hunk_repo
    # Get the unstaged diff — should have 2 hunks
    hunks = impl.get_file_diff("WORKING_TREE", "multi.txt")
    assert len(hunks) == 2

    # Stage only the first hunk
    impl.stage_hunk("multi.txt", hunks[0].header)

    # Now staged diff should have 1 hunk (the one we staged)
    staged = impl.get_staged_diff("multi.txt")
    assert len(staged) == 1
    assert "CHANGED line 2" in "".join(c for _, c in staged[0].lines)

    # Unstaged diff should still have 1 hunk (the one we didn't stage)
    remaining = impl.get_file_diff("WORKING_TREE", "multi.txt")
    assert len(remaining) == 1
    assert "CHANGED line 18" in "".join(c for _, c in remaining[0].lines)


def test_unstage_hunk_unstages_only_one_hunk(multi_hunk_repo):
    impl, path = multi_hunk_repo
    # Stage the whole file first
    impl.stage(["multi.txt"])

    # Staged diff should have 2 hunks
    staged = impl.get_staged_diff("multi.txt")
    assert len(staged) == 2

    # Unstage only the first hunk
    impl.unstage_hunk("multi.txt", staged[0].header)

    # Staged should now have 1 hunk
    staged_after = impl.get_staged_diff("multi.txt")
    assert len(staged_after) == 1
    assert "CHANGED line 18" in "".join(c for _, c in staged_after[0].lines)

    # Unstaged should have 1 hunk (the one we unstaged)
    unstaged = impl.get_file_diff("WORKING_TREE", "multi.txt")
    assert len(unstaged) == 1
    assert "CHANGED line 2" in "".join(c for _, c in unstaged[0].lines)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/infrastructure/test_hunk_staging.py -v
```

Expected: FAIL with `AttributeError: 'Pygit2Repository' object has no attribute 'stage_hunk'`

- [ ] **Step 3: Add port methods to `IRepositoryWriter`**

In `git_gui/domain/ports.py`, add after the existing `unstage` method:

```python
    def stage_hunk(self, path: str, hunk_header: str) -> None: ...
    def unstage_hunk(self, path: str, hunk_header: str) -> None: ...
```

- [ ] **Step 4: Implement `stage_hunk` and `unstage_hunk` in `Pygit2Repository`**

In `git_gui/infrastructure/pygit2_repo.py`, add `import subprocess` at the top, then add these methods after the existing `unstage` method:

```python
    def stage_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=False)
        if patch:
            subprocess.run(
                ["git", "apply", "--cached", "--unidiff-zero"],
                input=patch, cwd=self._repo.workdir,
                check=True, capture_output=True, text=True,
            )
            self._repo.index.read()

    def unstage_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=True)
        if patch:
            subprocess.run(
                ["git", "apply", "--cached", "--reverse", "--unidiff-zero"],
                input=patch, cwd=self._repo.workdir,
                check=True, capture_output=True, text=True,
            )
            self._repo.index.read()

    def _build_hunk_patch(self, path: str, hunk_header: str, staged: bool) -> str | None:
        if staged:
            if self._repo.head_is_unborn:
                empty_tree_oid = self._repo.TreeBuilder().write()
                empty_tree = self._repo.get(empty_tree_oid)
                diff = self._repo.index.diff_to_tree(empty_tree)
            else:
                head_commit = self._repo.head.peel(pygit2.Commit)
                diff = self._repo.index.diff_to_tree(head_commit.tree)
        else:
            diff = self._repo.diff()

        for patch in diff:
            if patch.delta.new_file.path != path and patch.delta.old_file.path != path:
                continue
            for hunk in patch.hunks:
                if hunk.header == hunk_header:
                    # Build minimal patch: diff header + single hunk
                    lines = [f"--- a/{path}\n", f"+++ b/{path}\n"]
                    lines.append(hunk.header)
                    for line in hunk.lines:
                        lines.append(f"{line.origin}{line.content}")
                    # Ensure last line ends with newline
                    if lines and not lines[-1].endswith("\n"):
                        lines[-1] += "\n"
                    return "".join(lines)
        return None
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/infrastructure/test_hunk_staging.py -v
```

Expected: all 2 tests PASS.

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add git_gui/domain/ports.py git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_hunk_staging.py
git commit -m "feat: add hunk-level staging and unstaging"
```

---

## Task 2: Application & Bus — StageHunk / UnstageHunk commands

**Files:**
- Modify: `git_gui/application/commands.py`
- Modify: `git_gui/presentation/bus.py`

**Context:** Wire the new port methods through the application and bus layers so the presentation can call `commands.stage_hunk.execute(path, header)`.

- [ ] **Step 1: Add `StageHunk` and `UnstageHunk` to `commands.py`**

At the end of `git_gui/application/commands.py`, add:

```python
class StageHunk:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str, hunk_header: str) -> None:
        self._writer.stage_hunk(path, hunk_header)


class UnstageHunk:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str, hunk_header: str) -> None:
        self._writer.unstage_hunk(path, hunk_header)
```

- [ ] **Step 2: Update `bus.py` imports and `CommandBus`**

In `git_gui/presentation/bus.py`, update the import:

```python
from git_gui.application.commands import (
    StageFiles, UnstageFiles, CreateCommit,
    Checkout, CreateBranch, DeleteBranch,
    Merge, Rebase, Push, Pull, Fetch,
    Stash, PopStash, StageHunk, UnstageHunk,
)
```

Add fields to the `CommandBus` dataclass:

```python
    stage_hunk: StageHunk
    unstage_hunk: UnstageHunk
```

Update `from_writer`:

```python
            stage_hunk=StageHunk(writer),
            unstage_hunk=UnstageHunk(writer),
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add git_gui/application/commands.py git_gui/presentation/bus.py
git commit -m "feat: wire StageHunk and UnstageHunk through command bus"
```

---

## Task 3: WorkingTreeModel — file list with checkboxes

**Files:**
- Create: `git_gui/presentation/widgets/working_tree_model.py`
- Create: `tests/presentation/test_working_tree_model.py`

**Context:** A `QAbstractListModel` that displays `FileStatus` items. Each row shows `"path  (delta)"` with a checkbox: checked = staged. Toggling the checkbox calls `stage_files` or `unstage_files` and emits `files_changed` so the parent widget can reload from git.

- [ ] **Step 1: Write the failing tests**

Create `tests/presentation/test_working_tree_model.py`:

```python
from unittest.mock import MagicMock
from PySide6.QtCore import Qt
from git_gui.domain.entities import FileStatus
from git_gui.presentation.widgets.working_tree_model import WorkingTreeModel


def _make_files():
    return [
        FileStatus(path="src/foo.py", status="staged", delta="modified"),
        FileStatus(path="src/bar.py", status="unstaged", delta="added"),
        FileStatus(path="README.md", status="staged", delta="deleted"),
    ]


def test_row_count(qtbot):
    model = WorkingTreeModel(MagicMock())
    model.reload(_make_files())
    assert model.rowCount() == 3


def test_display_role(qtbot):
    model = WorkingTreeModel(MagicMock())
    model.reload(_make_files())
    text = model.data(model.index(0), Qt.DisplayRole)
    assert "src/foo.py" in text
    assert "modified" in text


def test_check_state_staged(qtbot):
    model = WorkingTreeModel(MagicMock())
    model.reload(_make_files())
    assert model.data(model.index(0), Qt.CheckStateRole) == Qt.Checked


def test_check_state_unstaged(qtbot):
    model = WorkingTreeModel(MagicMock())
    model.reload(_make_files())
    assert model.data(model.index(1), Qt.CheckStateRole) == Qt.Unchecked


def test_user_role_returns_file_status(qtbot):
    model = WorkingTreeModel(MagicMock())
    model.reload(_make_files())
    fs = model.data(model.index(0), Qt.UserRole)
    assert isinstance(fs, FileStatus)
    assert fs.path == "src/foo.py"


def test_toggle_checkbox_calls_stage(qtbot):
    commands = MagicMock()
    model = WorkingTreeModel(commands)
    model.reload(_make_files())
    # Toggle unchecked (unstaged) → checked (stage it)
    model.setData(model.index(1), Qt.Checked, Qt.CheckStateRole)
    commands.stage_files.execute.assert_called_once_with(["src/bar.py"])


def test_toggle_checkbox_calls_unstage(qtbot):
    commands = MagicMock()
    model = WorkingTreeModel(commands)
    model.reload(_make_files())
    # Toggle checked (staged) → unchecked (unstage it)
    model.setData(model.index(0), Qt.Unchecked, Qt.CheckStateRole)
    commands.unstage_files.execute.assert_called_once_with(["src/foo.py"])


def test_flags_include_checkable(qtbot):
    model = WorkingTreeModel(MagicMock())
    model.reload(_make_files())
    flags = model.flags(model.index(0))
    assert flags & Qt.ItemIsUserCheckable
    assert flags & Qt.ItemIsSelectable
    assert flags & Qt.ItemIsEnabled
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/presentation/test_working_tree_model.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `WorkingTreeModel`**

Create `git_gui/presentation/widgets/working_tree_model.py`:

```python
# git_gui/presentation/widgets/working_tree_model.py
from __future__ import annotations
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal
from git_gui.domain.entities import FileStatus


class WorkingTreeModel(QAbstractListModel):
    files_changed = Signal()

    def __init__(self, commands, parent=None) -> None:
        super().__init__(parent)
        self._commands = commands
        self._files: list[FileStatus] = []

    def reload(self, files: list[FileStatus]) -> None:
        self.beginResetModel()
        self._files = list(files)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._files)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._files):
            return None
        fs = self._files[index.row()]
        if role == Qt.DisplayRole:
            return f"{fs.path}  ({fs.delta})"
        if role == Qt.CheckStateRole:
            return Qt.Checked if fs.status == "staged" else Qt.Unchecked
        if role == Qt.UserRole:
            return fs
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if role != Qt.CheckStateRole or not index.isValid():
            return False
        fs = self._files[index.row()]
        if value == Qt.Checked:
            self._commands.stage_files.execute([fs.path])
        else:
            self._commands.unstage_files.execute([fs.path])
        self.files_changed.emit()
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/presentation/test_working_tree_model.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/widgets/working_tree_model.py tests/presentation/test_working_tree_model.py
git commit -m "feat: add WorkingTreeModel with per-file staging checkboxes"
```

---

## Task 4: HunkDiffWidget — scrollable hunk diff with per-hunk checkboxes

**Files:**
- Create: `git_gui/presentation/widgets/hunk_diff.py`

**Context:** A `QScrollArea` containing a vertical list of hunk blocks. Each block has a `QCheckBox` header (checked = staged) and a read-only `QPlainTextEdit` showing the diff lines with the same formatting as commit diff (white text, green/red background). Toggling a checkbox calls `stage_hunk` or `unstage_hunk` and re-renders. No tests — presentation-only widget.

- [ ] **Step 1: Create `git_gui/presentation/widgets/hunk_diff.py`**

```python
# git_gui/presentation/widgets/hunk_diff.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import (
    QCheckBox, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import Hunk
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.domain.entities import WORKING_TREE_OID


class HunkDiffWidget(QWidget):
    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands
        self._current_path: str | None = None

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._scroll.setWidget(self._container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)

        # Diff formats
        self._fmt_added = QTextCharFormat()
        self._fmt_added.setForeground(QColor("white"))
        self._fmt_removed = QTextCharFormat()
        self._fmt_removed.setForeground(QColor("white"))
        self._fmt_header = QTextCharFormat()
        self._fmt_header.setForeground(QColor("#58a6ff"))
        self._fmt_default = QTextCharFormat()
        self._fmt_default.setForeground(QColor("white"))

        self._blk_added = QTextBlockFormat()
        self._blk_added.setBackground(QColor(35, 134, 54, 80))
        self._blk_removed = QTextBlockFormat()
        self._blk_removed.setBackground(QColor(248, 81, 73, 80))
        self._blk_default = QTextBlockFormat()

    def load_file(self, path: str) -> None:
        self._current_path = path
        self._render()

    def clear(self) -> None:
        self._current_path = None
        self._clear_layout()

    def _render(self) -> None:
        self._clear_layout()
        if self._current_path is None:
            return

        staged_hunks = self._queries.get_staged_diff.execute(self._current_path)
        unstaged_hunks = self._queries.get_file_diff.execute(
            WORKING_TREE_OID, self._current_path
        )

        for hunk in staged_hunks:
            self._add_hunk_block(hunk, is_staged=True)
        for hunk in unstaged_hunks:
            self._add_hunk_block(hunk, is_staged=False)

        self._layout.addStretch()

    def _add_hunk_block(self, hunk: Hunk, is_staged: bool) -> None:
        checkbox = QCheckBox(hunk.header.strip())
        checkbox.setChecked(is_staged)

        path = self._current_path
        header = hunk.header
        checkbox.toggled.connect(
            lambda checked, p=path, h=header: self._on_hunk_toggled(p, h, checked)
        )

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = editor.font()
        font.setFamily("Courier New")
        editor.setFont(font)
        editor.setMaximumHeight(len(hunk.lines) * editor.fontMetrics().height() + 16)

        cursor = editor.textCursor()
        for origin, content in hunk.lines:
            if origin == "+":
                cursor.setBlockFormat(self._blk_added)
                cursor.setCharFormat(self._fmt_added)
            elif origin == "-":
                cursor.setBlockFormat(self._blk_removed)
                cursor.setCharFormat(self._fmt_removed)
            else:
                cursor.setBlockFormat(self._blk_default)
                cursor.setCharFormat(self._fmt_default)
            cursor.insertText(content if content.endswith("\n") else content + "\n")
        editor.setTextCursor(cursor)

        self._layout.addWidget(checkbox)
        self._layout.addWidget(editor)

    def _on_hunk_toggled(self, path: str, hunk_header: str, checked: bool) -> None:
        if checked:
            self._commands.stage_hunk.execute(path, hunk_header)
        else:
            self._commands.unstage_hunk.execute(path, hunk_header)
        self._render()

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/hunk_diff.py
git commit -m "feat: add HunkDiffWidget with per-hunk staging checkboxes"
```

---

## Task 5: WorkingTreeWidget — 3-row layout

**Files:**
- Create: `git_gui/presentation/widgets/working_tree.py`

**Context:** The main working tree widget with 3 rows in a vertical splitter: commit toolbar (Row 1), file list (Row 2), hunk diff (Row 3). Row 1 has a `QPlainTextEdit` for the commit message and 3 buttons (Stage All, Unstage All, Commit). Row 2 is a `QListView` with `WorkingTreeModel`. Row 3 is a `HunkDiffWidget`. Emits `reload_requested` after commit or stage/unstage so MainWindow can refresh.

- [ ] **Step 1: Create `git_gui/presentation/widgets/working_tree.py`**

```python
# git_gui/presentation/widgets/working_tree.py
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QListView, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.widgets.working_tree_model import WorkingTreeModel
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget


class WorkingTreeWidget(QWidget):
    reload_requested = Signal()

    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands

        # ── Row 1: commit toolbar ────────────────────────────────────────────
        self._msg_edit = QPlainTextEdit()
        self._msg_edit.setPlaceholderText("Commit message...")
        self._msg_edit.setMaximumHeight(80)

        self._btn_stage_all = QPushButton("Stage All")
        self._btn_unstage_all = QPushButton("Unstage All")
        self._btn_commit = QPushButton("Commit")

        btn_layout = QVBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addWidget(self._btn_stage_all)
        btn_layout.addWidget(self._btn_unstage_all)
        btn_layout.addWidget(self._btn_commit)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(4, 4, 4, 4)
        toolbar_layout.addWidget(self._msg_edit, 1)
        toolbar_layout.addLayout(btn_layout)

        # ── Row 2: file list ─────────────────────────────────────────────────
        self._file_view = QListView()
        self._file_view.setEditTriggers(QListView.NoEditTriggers)

        self._file_model = WorkingTreeModel(commands, self)
        self._file_view.setModel(self._file_model)
        self._file_view.selectionModel().currentChanged.connect(self._on_file_selected)

        # ── Row 3: hunk diff ─────────────────────────────────────────────────
        self._hunk_diff = HunkDiffWidget(queries, commands, self)

        # ── Splitter ─────────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(toolbar)
        splitter.addWidget(self._file_view)
        splitter.addWidget(self._hunk_diff)
        splitter.setSizes([80, 200, 400])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        # ── Signals ──────────────────────────────────────────────────────────
        self._btn_stage_all.clicked.connect(self._on_stage_all)
        self._btn_unstage_all.clicked.connect(self._on_unstage_all)
        self._btn_commit.clicked.connect(self._on_commit)
        self._file_model.files_changed.connect(self._on_files_changed)

    def reload(self) -> None:
        files = self._queries.get_working_tree.execute()
        self._file_model.reload(files)
        self._hunk_diff.clear()

    def _on_file_selected(self, current, previous) -> None:
        if not current.isValid():
            return
        fs = self._file_model.data(current, Qt.UserRole)
        if fs is None:
            return
        self._hunk_diff.load_file(fs.path)

    def _on_stage_all(self) -> None:
        files = self._queries.get_working_tree.execute()
        paths = [f.path for f in files if f.status != "staged"]
        if paths:
            self._commands.stage_files.execute(paths)
            self._on_files_changed()

    def _on_unstage_all(self) -> None:
        files = self._queries.get_working_tree.execute()
        paths = [f.path for f in files if f.status == "staged"]
        if paths:
            self._commands.unstage_files.execute(paths)
            self._on_files_changed()

    def _on_commit(self) -> None:
        msg = self._msg_edit.toPlainText().strip()
        if not msg:
            return
        self._commands.create_commit.execute(msg)
        self._msg_edit.clear()
        self.reload_requested.emit()
        self.reload()

    def _on_files_changed(self) -> None:
        files = self._queries.get_working_tree.execute()
        self._file_model.reload(files)
        # Re-render hunk diff for currently selected file
        idx = self._file_view.currentIndex()
        if idx.isValid():
            fs = self._file_model.data(idx, Qt.UserRole)
            if fs:
                self._hunk_diff.load_file(fs.path)
            else:
                self._hunk_diff.clear()
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/working_tree.py
git commit -m "feat: add WorkingTreeWidget with 3-row layout"
```

---

## Task 6: DiffWidget cleanup + MainWindow stack switching

**Files:**
- Modify: `git_gui/presentation/widgets/diff.py`
- Modify: `git_gui/presentation/main_window.py`

**Context:** Remove all working tree code from `DiffWidget` (it's now commit-mode only). Move the `QStackedWidget` to `MainWindow` to switch between `DiffWidget` and `WorkingTreeWidget` based on the selected commit.

- [ ] **Step 1: Replace `git_gui/presentation/widgets/diff.py`**

```python
# git_gui/presentation/widgets/diff.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import (
    QListView, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget,
)
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.diff_model import DiffModel


class DiffWidget(QWidget):
    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._current_oid: str | None = None

        self._file_view = QListView()
        self._file_view.setEditTriggers(QListView.NoEditTriggers)
        self._diff_view = self._make_diff_editor()
        self._diff_model = DiffModel([])
        self._file_view.setModel(self._diff_model)
        self._file_view.selectionModel().currentChanged.connect(
            self._on_file_selected
        )

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._file_view)
        splitter.addWidget(self._diff_view)
        splitter.setSizes([200, 400])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        # Diff render formats
        self._fmt_added = QTextCharFormat()
        self._fmt_added.setForeground(QColor("white"))
        self._fmt_removed = QTextCharFormat()
        self._fmt_removed.setForeground(QColor("white"))
        self._fmt_header = QTextCharFormat()
        self._fmt_header.setForeground(QColor("#58a6ff"))
        self._fmt_default = QTextCharFormat()
        self._fmt_default.setForeground(QColor("white"))

        self._blk_added = QTextBlockFormat()
        self._blk_added.setBackground(QColor(35, 134, 54, 80))
        self._blk_removed = QTextBlockFormat()
        self._blk_removed.setBackground(QColor(248, 81, 73, 80))
        self._blk_default = QTextBlockFormat()

    def load_commit(self, oid: str) -> None:
        self._current_oid = oid
        files = self._queries.get_commit_files.execute(oid)
        self._diff_model.reload(files)
        self._diff_view.clear()
        if files:
            self._file_view.setCurrentIndex(self._diff_model.index(0))

    def _make_diff_editor(self) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = editor.font()
        font.setFamily("Courier New")
        editor.setFont(font)
        return editor

    def _on_file_selected(self, index) -> None:
        if not index.isValid() or self._current_oid is None:
            return
        file_status = self._diff_model.data(index, Qt.UserRole)
        if file_status is None:
            return
        hunks = self._queries.get_file_diff.execute(self._current_oid, file_status.path)
        self._render_diff(hunks)

    def _render_diff(self, hunks) -> None:
        self._diff_view.clear()
        cursor = self._diff_view.textCursor()
        for hunk in hunks:
            cursor.setBlockFormat(self._blk_default)
            cursor.setCharFormat(self._fmt_header)
            cursor.insertText(hunk.header + "\n")
            for origin, content in hunk.lines:
                if origin == "+":
                    cursor.setBlockFormat(self._blk_added)
                    cursor.setCharFormat(self._fmt_added)
                elif origin == "-":
                    cursor.setBlockFormat(self._blk_removed)
                    cursor.setCharFormat(self._fmt_removed)
                else:
                    cursor.setBlockFormat(self._blk_default)
                    cursor.setCharFormat(self._fmt_default)
                cursor.insertText(content if content.endswith("\n") else content + "\n")
        self._diff_view.setTextCursor(cursor)
```

- [ ] **Step 2: Replace `git_gui/presentation/main_window.py`**

```python
# git_gui/presentation/main_window.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QSplitter, QStackedWidget, QToolBar
from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.widgets.diff import DiffWidget
from git_gui.presentation.widgets.graph import GraphWidget
from git_gui.presentation.widgets.sidebar import SidebarWidget
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


class MainWindow(QMainWindow):
    def __init__(self, queries: QueryBus, commands: CommandBus, repo_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"git gui — {repo_path}")
        self.resize(1400, 800)

        self._commands = commands
        self._sidebar = SidebarWidget(queries, commands)
        self._graph = GraphWidget(queries, commands)
        self._diff = DiffWidget(queries, commands)
        self._working_tree = WorkingTreeWidget(queries, commands)

        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(self._diff)           # index 0: commit mode
        self._right_stack.addWidget(self._working_tree)    # index 1: working tree

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._graph)
        splitter.addWidget(self._right_stack)
        splitter.setSizes([220, 230, 950])

        self._toolbar = QToolBar("Main")
        self._reload_action = QAction("Reload", self)
        self._reload_action.setShortcut(QKeySequence(Qt.Key_F5))
        self._reload_action.triggered.connect(self._reload)
        self._toolbar.addAction(self._reload_action)
        self.addToolBar(self._toolbar)
        self.setCentralWidget(splitter)

        # Wire cross-widget signals
        self._graph.commit_selected.connect(self._on_commit_selected)
        self._working_tree.reload_requested.connect(self._reload)
        self._sidebar.branch_checkout_requested.connect(self._on_branch_changed)
        self._sidebar.branch_merge_requested.connect(
            lambda b: (commands.merge.execute(b), self._reload()))
        self._sidebar.branch_rebase_requested.connect(
            lambda b: (commands.rebase.execute(b), self._reload()))
        self._sidebar.branch_delete_requested.connect(
            lambda b: (commands.delete_branch.execute(b), self._reload()))
        self._sidebar.fetch_requested.connect(
            lambda r: (commands.fetch.execute(r), self._reload()))
        self._sidebar.branch_push_requested.connect(
            lambda b: (commands.push.execute("origin", b), self._reload()))

        self._reload()

    def _on_commit_selected(self, oid: str) -> None:
        if oid == WORKING_TREE_OID:
            self._right_stack.setCurrentIndex(1)
            self._working_tree.reload()
        else:
            self._right_stack.setCurrentIndex(0)
            self._diff.load_commit(oid)

    def _reload(self) -> None:
        self._sidebar.reload()
        self._graph.reload()

    def _on_branch_changed(self, branch: str) -> None:
        self._reload()
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add git_gui/presentation/widgets/diff.py git_gui/presentation/main_window.py
git commit -m "feat: extract WorkingTreeWidget, stack switching in MainWindow"
```

---

## Self-Review

**Spec coverage:**
- ✅ Row 1: commit message `QPlainTextEdit` + 3 buttons (Stage All, Unstage All, Commit)
- ✅ Row 2: file list with per-file checkbox (staged/unstaged), click to select with highlight
- ✅ Row 3: hunk diff with per-hunk checkbox for stage/unstage
- ✅ Domain: `stage_hunk`, `unstage_hunk` added to `IRepositoryWriter`
- ✅ Infrastructure: implemented via `git apply --cached`
- ✅ Commands: `StageHunk`, `UnstageHunk` wired through `CommandBus`
- ✅ `DiffWidget` cleaned up (commit-mode only)
- ✅ `MainWindow` stack switching between DiffWidget/WorkingTreeWidget
- ✅ `reload_requested` signal after commit

**Placeholder scan:** None found.

**Type consistency:**
- `stage_hunk(path: str, hunk_header: str)` consistent across ports → repo → command → bus → widget
- `unstage_hunk(path: str, hunk_header: str)` consistent across all layers
- `WorkingTreeModel` constructor takes `commands` — used in Task 3 tests and Task 5 widget
- `HunkDiffWidget.load_file(path: str)` called from `WorkingTreeWidget._on_file_selected`
- `files_changed` signal on `WorkingTreeModel` connected in `WorkingTreeWidget.__init__`
