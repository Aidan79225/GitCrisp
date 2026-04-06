# Working Detail: Discard & New-File Hunks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render hunks for newly added files, add a discard-hunk X button to unstaged hunks, and add a right-click "Discard changes" menu on the working file list — both gated by a confirmation dialog.

**Architecture:** Extend `pygit2_repo.py` with synthesised hunks for untracked files and two new writer methods (`discard_file`, `discard_hunk`). Add matching application commands and wire them through the bus. Update `HunkDiffWidget` to optionally show an X button on unstaged hunks. Update `WorkingTreeWidget` with a `QListView` context menu.

**Tech Stack:** Python 3, PySide6, pygit2, pytest.

**Spec:** `docs/superpowers/specs/2026-04-06-working-detail-discard-design.md`

---

## File Map

**Created:**
- (none)

**Modified:**
- `git_gui/infrastructure/pygit2_repo.py` — synthesise untracked hunks; add `discard_file`, `discard_hunk`
- `git_gui/domain/ports.py` — add two writer methods
- `git_gui/application/commands.py` — add `DiscardFile`, `DiscardHunk`
- `git_gui/presentation/bus.py` — register the two commands on `CommandBus`
- `git_gui/presentation/widgets/hunk_diff.py` — X button on unstaged hunks; new signal/handler
- `git_gui/presentation/widgets/working_tree.py` — right-click context menu; pass through
- `tests/infrastructure/test_reads.py` (or new `test_untracked_diff.py`) — synthesised hunks tests
- `tests/infrastructure/test_writes.py` (or new `test_discard.py`) — discard tests

---

## Task 1: Synthesised hunks for untracked files

**Files:**
- Modify: `git_gui/infrastructure/pygit2_repo.py:157-172`
- Test: `tests/infrastructure/test_untracked_diff.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_untracked_diff.py`:

```python
from pathlib import Path
from git_gui.infrastructure.pygit2_repo import Pygit2Repository
from git_gui.domain.entities import WORKING_TREE_OID


def _init(repo_path: Path) -> Pygit2Repository:
    impl = Pygit2Repository(str(repo_path))
    (repo_path / "seed.txt").write_text("seed\n")
    impl.stage(["seed.txt"])
    impl.commit("seed")
    return impl


def test_untracked_text_file_has_synthetic_hunk(repo_path):
    impl = _init(repo_path)
    (repo_path / "new.txt").write_text("alpha\nbeta\ngamma\n")
    hunks = impl.get_file_diff(WORKING_TREE_OID, "new.txt")
    assert len(hunks) == 1
    assert hunks[0].header.startswith("@@ -0,0 +1,3")
    origins = [o for o, _ in hunks[0].lines]
    assert origins == ["+", "+", "+"]
    contents = [c.rstrip("\n") for _, c in hunks[0].lines]
    assert contents == ["alpha", "beta", "gamma"]


def test_untracked_binary_file_shows_placeholder(repo_path):
    impl = _init(repo_path)
    (repo_path / "blob.bin").write_bytes(b"abc\x00def\x00ghi")
    hunks = impl.get_file_diff(WORKING_TREE_OID, "blob.bin")
    assert len(hunks) == 1
    assert hunks[0].lines[0][0] == "+"
    assert "Binary file" in hunks[0].lines[0][1]


def test_untracked_large_file_shows_placeholder(repo_path):
    impl = _init(repo_path)
    big = "x\n" * 6000
    (repo_path / "big.txt").write_text(big)
    hunks = impl.get_file_diff(WORKING_TREE_OID, "big.txt")
    assert len(hunks) == 1
    assert "Large file" in hunks[0].lines[0][1]
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `pytest tests/infrastructure/test_untracked_diff.py -v`
Expected: 3 failures — `get_file_diff` returns `[]` for untracked files.

- [ ] **Step 3: Implement synthesised hunk in `get_file_diff`**

Edit `git_gui/infrastructure/pygit2_repo.py`. Replace the body of `get_file_diff` (lines 157-172) with:

```python
    def get_file_diff(self, oid: str, path: str) -> list[Hunk]:
        if oid == WORKING_TREE_OID:
            diff = self._repo.diff()
            for patch in diff:
                if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                    return _diff_to_hunks(patch)
            # Not found in tracked diff — check if it's an untracked file
            status = self._repo.status_file(path) if path in self._repo.status() else None
            if status is not None and (status & pygit2.GIT_STATUS_WT_NEW):
                return _synthesise_untracked_hunk(self._repo.workdir, path)
            return []
        commit = self._repo.get(oid)
        if commit.parents:
            diff = self._repo.diff(commit.parents[0].tree, commit.tree)
        else:
            empty_tree_oid = self._repo.TreeBuilder().write()
            empty_tree = self._repo.get(empty_tree_oid)
            diff = self._repo.diff(empty_tree, commit.tree)
        for patch in diff:
            if patch.delta.new_file.path == path or patch.delta.old_file.path == path:
                return _diff_to_hunks(patch)
        return []
```

- [ ] **Step 4: Add the `_synthesise_untracked_hunk` helper**

Add this function at module scope in `git_gui/infrastructure/pygit2_repo.py` (near `_diff_to_hunks`):

```python
_UNTRACKED_MAX_LINES = 5000
_UNTRACKED_MAX_BYTES = 1_048_576


def _synthesise_untracked_hunk(workdir: str, path: str) -> list[Hunk]:
    import os
    full = os.path.join(workdir, path)
    try:
        size = os.path.getsize(full)
        with open(full, "rb") as f:
            head = f.read(8192)
        is_binary = b"\x00" in head
        if is_binary:
            return [Hunk(header="@@ -0,0 +1,1 @@",
                         lines=[("+", "Binary file\n")])]
        if size > _UNTRACKED_MAX_BYTES:
            return [Hunk(header="@@ -0,0 +1,1 @@",
                         lines=[("+", f"Large file ({size} bytes)\n")])]
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        lines = text.splitlines(keepends=True)
        if len(lines) > _UNTRACKED_MAX_LINES:
            return [Hunk(header="@@ -0,0 +1,1 @@",
                         lines=[("+", f"Large file ({len(lines)} lines, {size} bytes)\n")])]
        if not lines:
            return []
        return [Hunk(
            header=f"@@ -0,0 +1,{len(lines)} @@",
            lines=[("+", line if line.endswith("\n") else line + "\n") for line in lines],
        )]
    except OSError:
        return []
```

- [ ] **Step 5: Run the tests to confirm they pass**

Run: `pytest tests/infrastructure/test_untracked_diff.py -v`
Expected: 3 passing.

- [ ] **Step 6: Run the full infrastructure test suite to confirm no regressions**

Run: `pytest tests/infrastructure/ -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_untracked_diff.py
git commit -m "feat: render synthesised hunks for untracked files"
```

---

## Task 2: `discard_file` writer method + port + command

**Files:**
- Modify: `git_gui/domain/ports.py:25`
- Modify: `git_gui/infrastructure/pygit2_repo.py` (add `discard_file`)
- Modify: `git_gui/application/commands.py` (add `DiscardFile`)
- Test: `tests/infrastructure/test_discard.py` (new)

- [ ] **Step 1: Write failing tests for `discard_file`**

Create `tests/infrastructure/test_discard.py`:

```python
from pathlib import Path
from git_gui.infrastructure.pygit2_repo import Pygit2Repository


def _seed(repo_path: Path) -> Pygit2Repository:
    impl = Pygit2Repository(str(repo_path))
    (repo_path / "a.txt").write_text("original\n")
    impl.stage(["a.txt"])
    impl.commit("seed")
    return impl


def test_discard_modified_file_reverts_to_head(repo_path):
    impl = _seed(repo_path)
    (repo_path / "a.txt").write_text("modified\n")
    impl.discard_file("a.txt")
    assert (repo_path / "a.txt").read_text() == "original\n"


def test_discard_deleted_file_restores(repo_path):
    impl = _seed(repo_path)
    (repo_path / "a.txt").unlink()
    impl.discard_file("a.txt")
    assert (repo_path / "a.txt").read_text() == "original\n"


def test_discard_untracked_file_unlinks(repo_path):
    impl = _seed(repo_path)
    (repo_path / "new.txt").write_text("hello\n")
    impl.discard_file("new.txt")
    assert not (repo_path / "new.txt").exists()


def test_discard_staged_add_unstages_and_unlinks(repo_path):
    impl = _seed(repo_path)
    (repo_path / "added.txt").write_text("staged add\n")
    impl.stage(["added.txt"])
    impl.discard_file("added.txt")
    assert not (repo_path / "added.txt").exists()
    # Index should not contain it either
    assert "added.txt" not in [e.path for e in impl._repo.index]


def test_discard_modified_with_staged_changes_fully_resets(repo_path):
    impl = _seed(repo_path)
    (repo_path / "a.txt").write_text("staged change\n")
    impl.stage(["a.txt"])
    (repo_path / "a.txt").write_text("further unstaged\n")
    impl.discard_file("a.txt")
    assert (repo_path / "a.txt").read_text() == "original\n"
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/infrastructure/test_discard.py -v`
Expected: 5 failures (`AttributeError: 'Pygit2Repository' object has no attribute 'discard_file'`).

- [ ] **Step 3: Add `discard_file` to the writer port**

Edit `git_gui/domain/ports.py`. In the `IRepositoryWriter` Protocol (after `unstage_hunk` on line 29), add:

```python
    def discard_file(self, path: str) -> None: ...
    def discard_hunk(self, path: str, hunk_header: str) -> None: ...
```

- [ ] **Step 4: Implement `discard_file` in `Pygit2Repository`**

Edit `git_gui/infrastructure/pygit2_repo.py`. Add this method right after `unstage_hunk` (around line 397):

```python
    def discard_file(self, path: str) -> None:
        import os
        full = os.path.join(self._repo.workdir, path)
        head_has_blob = False
        if not self._repo.head_is_unborn:
            head_commit = self._repo.head.peel(pygit2.Commit)
            try:
                head_commit.tree[path]
                head_has_blob = True
            except KeyError:
                head_has_blob = False

        if head_has_blob:
            # Reset both index and working tree to HEAD content for this path
            head_commit = self._repo.head.peel(pygit2.Commit)
            entry = head_commit.tree[path]
            self._repo.index.add(
                pygit2.IndexEntry(path, entry.id, entry.filemode)
            )
            self._repo.index.write()
            blob = self._repo.get(entry.id)
            os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
            with open(full, "wb") as f:
                f.write(blob.data)
        else:
            # No HEAD blob: unstage if present, then unlink from disk
            try:
                self._repo.index.remove(path)
                self._repo.index.write()
            except (KeyError, OSError):
                pass
            if os.path.exists(full):
                os.remove(full)
```

- [ ] **Step 5: Run discard tests to confirm they pass**

Run: `pytest tests/infrastructure/test_discard.py -v`
Expected: 5 passing.

- [ ] **Step 6: Add `DiscardFile` application command**

Edit `git_gui/application/commands.py`. Append:

```python
class DiscardFile:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str) -> None:
        self._writer.discard_file(path)
```

- [ ] **Step 7: Run full test suite**

Run: `pytest tests/ -v`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add git_gui/domain/ports.py git_gui/infrastructure/pygit2_repo.py git_gui/application/commands.py tests/infrastructure/test_discard.py
git commit -m "feat: add discard_file writer and DiscardFile command"
```

---

## Task 3: `discard_hunk` writer method + command

**Files:**
- Modify: `git_gui/infrastructure/pygit2_repo.py` (add `discard_hunk`)
- Modify: `git_gui/application/commands.py` (add `DiscardHunk`)
- Test: `tests/infrastructure/test_discard.py` (extend)

- [ ] **Step 1: Append failing tests for `discard_hunk`**

Append to `tests/infrastructure/test_discard.py`:

```python
def test_discard_hunk_reverts_only_that_hunk(repo_path):
    impl = Pygit2Repository(str(repo_path))
    lines = [f"line {i}\n" for i in range(1, 21)]
    (repo_path / "multi.txt").write_text("".join(lines))
    impl.stage(["multi.txt"])
    impl.commit("seed multi")

    lines[1] = "CHANGED line 2\n"
    lines[17] = "CHANGED line 18\n"
    (repo_path / "multi.txt").write_text("".join(lines))

    from git_gui.domain.entities import WORKING_TREE_OID
    hunks = impl.get_file_diff(WORKING_TREE_OID, "multi.txt")
    assert len(hunks) == 2

    # Discard the first hunk only
    impl.discard_hunk("multi.txt", hunks[0].header)

    text = (repo_path / "multi.txt").read_text()
    assert "line 2\n" in text          # reverted
    assert "CHANGED line 2" not in text
    assert "CHANGED line 18\n" in text  # untouched
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/infrastructure/test_discard.py::test_discard_hunk_reverts_only_that_hunk -v`
Expected: AttributeError.

- [ ] **Step 3: Implement `discard_hunk`**

Edit `git_gui/infrastructure/pygit2_repo.py`. Add right below `discard_file`:

```python
    def discard_hunk(self, path: str, hunk_header: str) -> None:
        patch = self._build_hunk_patch(path, hunk_header, staged=False)
        if patch:
            subprocess.run(
                ["git", "apply", "--reverse"],
                input=patch.encode("utf-8"), cwd=self._repo.workdir,
                check=True, capture_output=True, **subprocess_kwargs(),
            )
            self._repo.index.read()
```

Note: this mirrors `unstage_hunk` (which uses `--cached --reverse`); the difference is no `--cached`, so it touches the working tree only — exactly what discard means.

- [ ] **Step 4: Run test to confirm pass**

Run: `pytest tests/infrastructure/test_discard.py::test_discard_hunk_reverts_only_that_hunk -v`
Expected: PASS.

- [ ] **Step 5: Add `DiscardHunk` application command**

Append to `git_gui/application/commands.py`:

```python
class DiscardHunk:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str, hunk_header: str) -> None:
        self._writer.discard_hunk(path, hunk_header)
```

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py git_gui/application/commands.py tests/infrastructure/test_discard.py
git commit -m "feat: add discard_hunk writer and DiscardHunk command"
```

---

## Task 4: Wire `DiscardFile` and `DiscardHunk` into `CommandBus`

**Files:**
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Update the imports**

Edit `git_gui/presentation/bus.py`. In the `from git_gui.application.commands import (...)` block, add `DiscardFile, DiscardHunk` to the list.

- [ ] **Step 2: Add fields to `CommandBus`**

In the `@dataclass class CommandBus` block, after `unstage_hunk: UnstageHunk`, add:

```python
    discard_file: DiscardFile
    discard_hunk: DiscardHunk
```

- [ ] **Step 3: Add construction in `from_writer`**

In `CommandBus.from_writer`, after `unstage_hunk=UnstageHunk(writer),`, add:

```python
            discard_file=DiscardFile(writer),
            discard_hunk=DiscardHunk(writer),
```

- [ ] **Step 4: Run the app's smoke import to verify wiring**

Run: `python -c "from git_gui.presentation.bus import CommandBus; print(CommandBus.__dataclass_fields__.keys())"`
Expected: includes `discard_file` and `discard_hunk` with no import errors.

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/bus.py
git commit -m "feat: register DiscardFile and DiscardHunk on CommandBus"
```

---

## Task 5: Discard-hunk X button in `HunkDiffWidget`

**Files:**
- Modify: `git_gui/presentation/widgets/hunk_diff.py`

This is a UI change with no automated test (PySide6 widget rendering); manual verification at the end.

- [ ] **Step 1: Add an `is_untracked` flag plumbed from the loader**

Edit `git_gui/presentation/widgets/hunk_diff.py`.

In `_LoadSignals` (line 14), change the signal signature:

```python
class _LoadSignals(QObject):
    done = Signal(str, list, list, bool)  # path, staged_hunks, unstaged_hunks, is_untracked
```

In `_fetch_and_render` (lines 69-84), update the worker:

```python
        def _worker():
            staged_hunks = queries.get_staged_diff.execute(path)
            unstaged_hunks = queries.get_file_diff.execute(WORKING_TREE_OID, path)
            # untracked when there is content in unstaged but nothing staged AND no header has @@ -<n>
            is_untracked = (
                not staged_hunks
                and bool(unstaged_hunks)
                and unstaged_hunks[0].header.startswith("@@ -0,0")
            )
            signals.done.emit(path, staged_hunks, unstaged_hunks, is_untracked)
```

Update `_on_load_done` signature and pass through:

```python
    def _on_load_done(self, path: str, staged_hunks: list[Hunk],
                      unstaged_hunks: list[Hunk], is_untracked: bool) -> None:
        if path != self._current_path:
            return
        self._clear_layout()
        for hunk in staged_hunks:
            self._add_hunk_block(hunk, is_staged=True, is_untracked=False)
        for hunk in unstaged_hunks:
            self._add_hunk_block(hunk, is_staged=False, is_untracked=is_untracked)
        self._layout.addStretch()
```

Update `_render_sync` similarly:

```python
    def _render_sync(self) -> None:
        self._clear_layout()
        if self._current_path is None:
            return
        staged_hunks = self._queries.get_staged_diff.execute(self._current_path)
        unstaged_hunks = self._queries.get_file_diff.execute(
            WORKING_TREE_OID, self._current_path
        )
        is_untracked = (
            not staged_hunks
            and bool(unstaged_hunks)
            and unstaged_hunks[0].header.startswith("@@ -0,0")
        )
        for hunk in staged_hunks:
            self._add_hunk_block(hunk, is_staged=True, is_untracked=False)
        for hunk in unstaged_hunks:
            self._add_hunk_block(hunk, is_staged=False, is_untracked=is_untracked)
        self._layout.addStretch()
```

- [ ] **Step 2: Add a `discard_hunk_requested` signal**

Near `hunk_toggled = Signal()` (line 19) add:

```python
    discard_hunk_requested = Signal(str, str)  # path, hunk_header
```

- [ ] **Step 3: Update imports for the X button**

Change the PySide6 imports at the top of the file from:

```python
from PySide6.QtWidgets import (
    QCheckBox, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget,
)
```

to:

```python
from PySide6.QtGui import QColor, QIcon, QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QMessageBox, QPlainTextEdit, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)
```

(Remove the existing `from PySide6.QtGui import QColor, QTextBlockFormat, QTextCharFormat` line — it is now combined.)

- [ ] **Step 4: Update `_add_hunk_block` signature and add the X button**

Replace `_add_hunk_block` (lines 119-169) with:

```python
    def _add_hunk_block(self, hunk: Hunk, is_staged: bool, is_untracked: bool) -> None:
        checkbox = QCheckBox(hunk.header.strip())
        checkbox.setChecked(is_staged)

        path = self._current_path
        header = hunk.header
        checkbox.toggled.connect(
            lambda checked, p=path, h=header: self._on_hunk_toggled(p, h, checked)
        )

        # Header row: checkbox on the left, optional X button on the right
        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(checkbox)
        header_layout.addStretch()
        if not is_staged and not is_untracked:
            x_btn = QToolButton()
            x_btn.setIcon(QIcon("arts/ic_close.svg"))
            x_btn.setToolTip("Discard this hunk")
            x_btn.setAutoRaise(True)
            x_btn.clicked.connect(
                lambda _=False, p=path, h=header: self._on_discard_hunk_clicked(p, h)
            )
            header_layout.addWidget(x_btn)

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        font = editor.font()
        font.setFamily("Courier New")
        editor.setFont(font)

        old_line, new_line = self._parse_hunk_header(hunk.header)
        cursor = editor.textCursor()
        for origin, content in hunk.lines:
            if origin == "+":
                cursor.setBlockFormat(self._blk_added)
                cursor.setCharFormat(self._fmt_added)
                prefix = f"     {new_line:>4}  "
                new_line += 1
            elif origin == "-":
                cursor.setBlockFormat(self._blk_removed)
                cursor.setCharFormat(self._fmt_removed)
                prefix = f"{old_line:>4}       "
                old_line += 1
            else:
                cursor.setBlockFormat(self._blk_default)
                cursor.setCharFormat(self._fmt_default)
                prefix = f"{old_line:>4} {new_line:>4}  "
                old_line += 1
                new_line += 1
            line = content if content.endswith("\n") else content + "\n"
            cursor.insertText(prefix + line)
        editor.setTextCursor(cursor)

        line_height = editor.fontMetrics().lineSpacing()
        margins = editor.contentsMargins()
        doc_margin = editor.document().documentMargin() * 2
        total_height = int(len(hunk.lines) * line_height + doc_margin + margins.top() + margins.bottom() + 4)
        editor.setFixedHeight(total_height)

        self._layout.addWidget(header_row)
        self._layout.addWidget(editor)
```

- [ ] **Step 5: Add the discard click handler**

Add this method below `_on_hunk_toggled`:

```python
    def _on_discard_hunk_clicked(self, path: str, hunk_header: str) -> None:
        reply = QMessageBox.question(
            self,
            "Discard hunk",
            "Discard this hunk? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._commands.discard_hunk.execute(path, hunk_header)
        self._render_sync()
        self.discard_hunk_requested.emit(path, hunk_header)
```

- [ ] **Step 6: Smoke-import the module**

Run: `python -c "from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget; print('ok')"`
Expected: `ok` with no errors.

- [ ] **Step 7: Run full test suite**

Run: `pytest tests/ -v`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/widgets/hunk_diff.py
git commit -m "feat: add discard-hunk X button to unstaged hunks"
```

---

## Task 6: Right-click "Discard changes" menu on file list

**Files:**
- Modify: `git_gui/presentation/widgets/working_tree.py`

- [ ] **Step 1: Add the context menu policy and signal connection**

Edit `git_gui/presentation/widgets/working_tree.py`. Update the imports to include `QMenu` and `QMessageBox`:

```python
from PySide6.QtWidgets import (
    QHBoxLayout, QListView, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QVBoxLayout, QWidget,
)
```

After the existing line `self._file_view.selectionModel().currentChanged.connect(self._on_file_selected)` (line 109), add:

```python
        self._file_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._file_view.customContextMenuRequested.connect(self._on_file_context_menu)
```

- [ ] **Step 2: Add the menu handler**

Add this method to `WorkingTreeWidget` (e.g., right after `_on_file_selected`):

```python
    def _on_file_context_menu(self, pos) -> None:
        index = self._file_view.indexAt(pos)
        if not index.isValid():
            return
        fs = self._file_model.data(index, Qt.UserRole)
        if fs is None:
            return
        menu = QMenu(self._file_view)
        discard_action = menu.addAction("Discard changes")
        chosen = menu.exec(self._file_view.viewport().mapToGlobal(pos))
        if chosen is discard_action:
            self._discard_file(fs.path)

    def _discard_file(self, path: str) -> None:
        reply = QMessageBox.question(
            self,
            "Discard changes",
            f"Discard all changes to {path}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._commands.discard_file.execute(path)
        self._on_files_changed()
```

- [ ] **Step 3: Smoke-import the module**

Run: `python -c "from git_gui.presentation.widgets.working_tree import WorkingTreeWidget; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/ -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/widgets/working_tree.py
git commit -m "feat: add right-click Discard changes menu on file list"
```

---

## Task 7: Manual verification

- [ ] **Step 1: Launch the app**

Run: `python main.py`

- [ ] **Step 2: Verify Feature 1 (untracked hunks)**

In a working repo, create a brand-new text file. Select it in the file list. Confirm the right-hand panel shows the file content as a single `+` hunk with header `@@ -0,0 +1,N @@`.

Then create a binary file (e.g., copy a small PNG). Confirm the panel shows `Binary file` as a single line.

- [ ] **Step 3: Verify Feature 2 (X button)**

Modify a tracked file to create at least two hunks. Confirm each unstaged hunk has an X button at the right edge of its header. Confirm:
- Staged hunks do **not** show X.
- Untracked file hunks do **not** show X.
- Clicking X opens "Discard this hunk?" dialog. No reverts the file. Yes removes that single hunk and the rest remain.

- [ ] **Step 4: Verify Feature 3 (right-click menu)**

Right-click each file row type (modified, deleted, untracked, staged-add). Confirm "Discard changes" appears in each case. Click it; confirm the dialog wording shows the correct file path; choose Yes; confirm the file fully reverts/disappears as specified in the spec table.

- [ ] **Step 5: No commit**

Manual verification step only.

---

## Self-Review Notes

- Spec coverage: Feature 1 → Task 1; Feature 2 → Tasks 3, 4, 5; Feature 3 → Tasks 2, 4, 6. Shared plumbing → Tasks 2, 3, 4. ✓
- Out-of-scope items (staged-side hunk discard, multi-select, undo) are intentionally absent. ✓
- Type consistency: writer methods named `discard_file` / `discard_hunk` everywhere; command classes `DiscardFile` / `DiscardHunk`; bus fields `discard_file` / `discard_hunk`. Signal `discard_hunk_requested(str, str)`. ✓
- No placeholders. ✓
