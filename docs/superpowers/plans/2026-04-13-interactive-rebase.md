# Interactive Rebase (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a commit list editor dialog (pick/squash/fixup/drop + reorder) for interactive rebase, triggered from the graph context menu, executing via `git rebase -i` with a custom `GIT_SEQUENCE_EDITOR`.

**Architecture:** New reader method `get_commit_range` walks HEAD→target to collect the rebasing commits. New writer method `interactive_rebase` writes a todo file and runs `git rebase -i` with `GIT_SEQUENCE_EDITOR` pointing at it. A new `InteractiveRebaseDialog` (QDialog with QTableWidget) lets the user assign actions and reorder rows. Graph context menu gets new "Interactive rebase onto" entries. Main window wires the signals and orchestrates the flow.

**Tech Stack:** Python, PySide6 (Qt), pygit2, subprocess, pytest, pytest-qt, uv.

**Spec:** `docs/superpowers/specs/2026-04-13-interactive-rebase-design.md`

---

## File Structure

**New:**
- `git_gui/presentation/dialogs/interactive_rebase_dialog.py`
- `tests/presentation/dialogs/test_interactive_rebase_dialog.py`

**Modified:**
- `git_gui/domain/ports.py`
- `git_gui/infrastructure/pygit2_repo.py`
- `git_gui/application/queries.py`
- `git_gui/application/commands.py`
- `git_gui/presentation/bus.py`
- `git_gui/presentation/widgets/graph.py`
- `git_gui/presentation/main_window.py`

**Test files modified:**
- `tests/infrastructure/test_reads.py`
- `tests/infrastructure/test_writes.py`
- `tests/application/test_queries.py`
- `tests/application/test_commands.py`

---

## Task 1: Add ports for `get_commit_range` and `interactive_rebase`

**Files:**
- Modify: `git_gui/domain/ports.py`

- [ ] **Step 1: Add reader method**

In `git_gui/domain/ports.py`, add to the `IRepositoryReader` protocol body:

```python
    def get_commit_range(self, head_oid: str, base_oid: str) -> list[Commit]: ...
```

- [ ] **Step 2: Add writer method**

Add to `IRepositoryWriter` protocol body:

```python
    def interactive_rebase(self, target_oid: str, entries: list[tuple[str, str]]) -> None: ...
```

- [ ] **Step 3: Verify**

Run: `uv run python -c "from git_gui.domain.ports import IRepositoryReader, IRepositoryWriter; print('ok')"`

- [ ] **Step 4: Commit**

```bash
git add git_gui/domain/ports.py
git commit -m "feat(domain): add get_commit_range and interactive_rebase ports"
```

---

## Task 2: Implement `get_commit_range` (TDD)

**Files:**
- Test: `tests/infrastructure/test_reads.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Write failing test**

Read the existing fixture pattern in `tests/infrastructure/test_reads.py` (`repo_impl`, `repo_path`). Append:

```python
def test_get_commit_range_returns_oldest_first(repo_impl, repo_path):
    """Create A → B → C chain. Range from C (HEAD) to A should return [B, C] oldest-first."""
    # The conftest fixture creates an initial commit (A).
    head_a = repo_impl.get_head_oid()

    (repo_path / "b.txt").write_text("b")
    repo_impl.stage(["b.txt"])
    commit_b = repo_impl.commit("commit B")

    (repo_path / "c.txt").write_text("c")
    repo_impl.stage(["c.txt"])
    commit_c = repo_impl.commit("commit C")

    result = repo_impl.get_commit_range(commit_c.oid, head_a)

    assert len(result) == 2
    assert result[0].oid == commit_b.oid  # oldest first
    assert result[1].oid == commit_c.oid


def test_get_commit_range_empty_when_same(repo_impl, repo_path):
    """When head_oid == base_oid, the range is empty."""
    head = repo_impl.get_head_oid()
    result = repo_impl.get_commit_range(head, head)
    assert result == []


def test_get_commit_range_single_commit(repo_impl, repo_path):
    """A → B: range from B to A returns [B]."""
    head_a = repo_impl.get_head_oid()
    (repo_path / "b.txt").write_text("b")
    repo_impl.stage(["b.txt"])
    commit_b = repo_impl.commit("commit B")

    result = repo_impl.get_commit_range(commit_b.oid, head_a)
    assert len(result) == 1
    assert result[0].oid == commit_b.oid
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/infrastructure/test_reads.py -v -k get_commit_range`

- [ ] **Step 3: Implement**

In `git_gui/infrastructure/pygit2_repo.py`, add to `Pygit2Repository`:

```python
def get_commit_range(self, head_oid: str, base_oid: str) -> list[Commit]:
    """Return commits from head_oid back to base_oid (exclusive), oldest-first.

    Walks from head_oid using topological + time sort, collects commits
    until base_oid is reached (base_oid itself is excluded), then reverses
    to return oldest-first order — matching git rebase -i's todo convention.
    """
    if head_oid == base_oid:
        return []
    walker = self._repo.walk(
        head_oid,
        pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_TIME,
    )
    collected: list[Commit] = []
    for c in walker:
        if str(c.id) == base_oid:
            break
        collected.append(_commit_to_entity(c))
    collected.reverse()
    return collected
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/infrastructure/test_reads.py -v -k get_commit_range`

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_reads.py
git commit -m "feat(infra): implement get_commit_range (oldest-first)"
```

---

## Task 3: Implement `interactive_rebase` (TDD)

**Files:**
- Test: `tests/infrastructure/test_writes.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Write failing test**

Read the fixture pattern in `tests/infrastructure/test_writes.py`. Append:

```python
def test_interactive_rebase_squash(repo_impl, repo_path):
    """Squash 3 commits into 2 by squashing the last into its predecessor."""
    # Create A → B → C chain
    (repo_path / "b.txt").write_text("b")
    repo_impl.stage(["b.txt"])
    commit_b = repo_impl.commit("commit B")

    (repo_path / "c.txt").write_text("c")
    repo_impl.stage(["c.txt"])
    commit_c = repo_impl.commit("commit C")

    # Get the initial commit oid (the base)
    commits = repo_impl.get_commits(limit=10)
    base_oid = commits[-1].oid  # the initial commit (oldest)

    # Squash C into B
    entries = [
        ("pick", commit_b.oid),
        ("squash", commit_c.oid),
    ]
    repo_impl.interactive_rebase(base_oid, entries)

    # After rebase: should have initial commit + one squashed commit = 2 total
    new_commits = repo_impl.get_commits(limit=10)
    assert len(new_commits) == 2
    # The squashed commit should contain both files
    import os
    assert os.path.exists(repo_path / "b.txt")
    assert os.path.exists(repo_path / "c.txt")


def test_interactive_rebase_drop(repo_impl, repo_path):
    """Drop the last commit."""
    (repo_path / "b.txt").write_text("b")
    repo_impl.stage(["b.txt"])
    commit_b = repo_impl.commit("commit B")

    (repo_path / "c.txt").write_text("c")
    repo_impl.stage(["c.txt"])
    commit_c = repo_impl.commit("commit C")

    commits = repo_impl.get_commits(limit=10)
    base_oid = commits[-1].oid

    entries = [
        ("pick", commit_b.oid),
        ("drop", commit_c.oid),
    ]
    repo_impl.interactive_rebase(base_oid, entries)

    new_commits = repo_impl.get_commits(limit=10)
    assert len(new_commits) == 2  # initial + B only
    import os
    assert os.path.exists(repo_path / "b.txt")
    assert not os.path.exists(repo_path / "c.txt")
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/infrastructure/test_writes.py -v -k interactive_rebase`

- [ ] **Step 3: Implement**

In `git_gui/infrastructure/pygit2_repo.py`, add to `Pygit2Repository`:

```python
def interactive_rebase(self, target_oid: str, entries: list[tuple[str, str]]) -> None:
    """Run git rebase -i with a pre-built todo file.

    *entries* is a list of (action, oid) tuples in replay order.
    Actions: "pick", "squash", "fixup", "drop".
    """
    import sys
    import tempfile

    # Build the todo file content
    todo_lines = [f"{action} {oid}" for action, oid in entries]
    todo_content = "\n".join(todo_lines) + "\n"

    # Write to a temp file
    todo_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8",
    )
    todo_file.write(todo_content)
    todo_file.close()

    env = self._git_env
    python = sys.executable.replace("\\", "/")
    todo_path = todo_file.name.replace("\\", "/")
    env["GIT_SEQUENCE_EDITOR"] = (
        f'{python} -c "'
        f"import shutil,sys; shutil.copy('{todo_path}', sys.argv[1])"
        f'"'
    )
    # Prevent interactive editor from opening for squash/fixup messages
    env["GIT_EDITOR"] = "true"

    try:
        result = subprocess.run(
            ["git", "rebase", "-i", target_oid],
            cwd=self._repo.workdir, capture_output=True, text=True,
            env=env, **subprocess_kwargs(),
        )
        if result.returncode != 0:
            # Check if we're in a conflict state — let the banner handle it
            state = self._repo.state()
            rebase_states = set()
            for name in ("GIT_REPOSITORY_STATE_REBASE",
                         "GIT_REPOSITORY_STATE_REBASE_INTERACTIVE",
                         "GIT_REPOSITORY_STATE_REBASE_MERGE"):
                const = getattr(pygit2, name, None)
                if const is not None:
                    rebase_states.add(const)
            if state in rebase_states:
                return  # conflict — Spec C banner will handle
            msg = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            raise RuntimeError(msg)
    finally:
        try:
            os.unlink(todo_file.name)
        except OSError:
            pass
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/infrastructure/test_writes.py -v -k interactive_rebase`

- [ ] **Step 5: Full suite**

Run: `uv run pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_writes.py
git commit -m "feat(infra): implement interactive_rebase via GIT_SEQUENCE_EDITOR"
```

---

## Task 4: Add application queries and commands (TDD)

**Files:**
- Test: `tests/application/test_queries.py`, `tests/application/test_commands.py`
- Modify: `git_gui/application/queries.py`, `git_gui/application/commands.py`

- [ ] **Step 1: Write failing query test**

Append to `tests/application/test_queries.py`:

```python
from git_gui.application.queries import GetCommitRange


class _FakeCommitRangeReader:
    def get_commit_range(self, head_oid, base_oid):
        return [f"commit_{head_oid}_{base_oid}"]


def test_get_commit_range_passthrough():
    q = GetCommitRange(_FakeCommitRangeReader())
    assert q.execute("head", "base") == ["commit_head_base"]
```

- [ ] **Step 2: Write failing command test**

Append to `tests/application/test_commands.py`:

```python
from git_gui.application.commands import InteractiveRebase


class _FakeInteractiveRebaseWriter:
    def __init__(self):
        self.called_with = None
    def interactive_rebase(self, target_oid, entries):
        self.called_with = (target_oid, entries)


def test_interactive_rebase_delegates():
    w = _FakeInteractiveRebaseWriter()
    entries = [("pick", "abc"), ("squash", "def")]
    InteractiveRebase(w).execute("target123", entries)
    assert w.called_with == ("target123", entries)
```

- [ ] **Step 3: Run — expect FAIL**

Run: `uv run pytest tests/application/ -v -k "commit_range or interactive_rebase_delegates"`

- [ ] **Step 4: Implement query**

Append to `git_gui/application/queries.py`:

```python
class GetCommitRange:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, head_oid: str, base_oid: str) -> list[Commit]:
        return self._reader.get_commit_range(head_oid, base_oid)
```

- [ ] **Step 5: Implement command**

Append to `git_gui/application/commands.py`:

```python
class InteractiveRebase:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, target_oid: str, entries: list[tuple[str, str]]) -> None:
        self._writer.interactive_rebase(target_oid, entries)
```

- [ ] **Step 6: Run — expect PASS**

Run: `uv run pytest tests/application/ -v -k "commit_range or interactive_rebase_delegates"`

- [ ] **Step 7: Commit**

```bash
git add git_gui/application/queries.py git_gui/application/commands.py tests/application/test_queries.py tests/application/test_commands.py
git commit -m "feat(application): add GetCommitRange query and InteractiveRebase command"
```

---

## Task 5: Wire into bus

**Files:**
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Update imports**

Add `GetCommitRange` to the queries import. Add `InteractiveRebase` to the commands import.

- [ ] **Step 2: Add to QueryBus**

Add `get_commit_range: GetCommitRange` field and `get_commit_range=GetCommitRange(reader),` in `from_reader`.

- [ ] **Step 3: Add to CommandBus**

Add `interactive_rebase: InteractiveRebase` field and `interactive_rebase=InteractiveRebase(writer),` in `from_writer`.

- [ ] **Step 4: Verify**

Run: `uv run python -c "from git_gui.presentation.bus import QueryBus, CommandBus; print('ok')"`

- [ ] **Step 5: Full suite**

Run: `uv run pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/bus.py
git commit -m "feat(bus): wire GetCommitRange and InteractiveRebase"
```

---

## Task 6: Create InteractiveRebaseDialog (TDD)

**Files:**
- Create: `git_gui/presentation/dialogs/interactive_rebase_dialog.py`
- Create: `tests/presentation/dialogs/test_interactive_rebase_dialog.py`

- [ ] **Step 1: Write failing tests**

Create `tests/presentation/dialogs/test_interactive_rebase_dialog.py`:

```python
"""Tests for InteractiveRebaseDialog."""
from __future__ import annotations
from datetime import datetime

import pytest
from PySide6.QtWidgets import QComboBox, QDialogButtonBox

from git_gui.domain.entities import Commit
from git_gui.presentation.dialogs.interactive_rebase_dialog import (
    InteractiveRebaseDialog,
)


def _commits():
    return [
        Commit(oid="aaa111", message="first commit", author="a", timestamp=datetime.now(), parents=[]),
        Commit(oid="bbb222", message="second commit", author="a", timestamp=datetime.now(), parents=["aaa111"]),
        Commit(oid="ccc333", message="third commit", author="a", timestamp=datetime.now(), parents=["bbb222"]),
    ]


def test_default_action_is_pick(qtbot):
    dlg = InteractiveRebaseDialog(_commits(), "main")
    qtbot.addWidget(dlg)
    for row in range(dlg._table.rowCount()):
        combo = dlg._table.cellWidget(row, 0)
        assert combo.currentText() == "pick"


def test_rows_match_commit_count(qtbot):
    commits = _commits()
    dlg = InteractiveRebaseDialog(commits, "main")
    qtbot.addWidget(dlg)
    assert dlg._table.rowCount() == 3


def test_commit_order_is_oldest_first(qtbot):
    commits = _commits()
    dlg = InteractiveRebaseDialog(commits, "main")
    qtbot.addWidget(dlg)
    # First row should be the oldest commit
    assert dlg._table.item(0, 1).text() == "aaa111"[:7]


def test_squash_on_first_row_disables_execute(qtbot):
    dlg = InteractiveRebaseDialog(_commits(), "main")
    qtbot.addWidget(dlg)
    combo = dlg._table.cellWidget(0, 0)
    combo.setCurrentText("squash")
    execute_btn = dlg._buttons.button(QDialogButtonBox.Ok)
    assert execute_btn.isEnabled() is False


def test_fixup_on_first_row_disables_execute(qtbot):
    dlg = InteractiveRebaseDialog(_commits(), "main")
    qtbot.addWidget(dlg)
    combo = dlg._table.cellWidget(0, 0)
    combo.setCurrentText("fixup")
    execute_btn = dlg._buttons.button(QDialogButtonBox.Ok)
    assert execute_btn.isEnabled() is False


def test_pick_on_first_row_enables_execute(qtbot):
    dlg = InteractiveRebaseDialog(_commits(), "main")
    qtbot.addWidget(dlg)
    # Change to squash then back to pick
    combo = dlg._table.cellWidget(0, 0)
    combo.setCurrentText("squash")
    combo.setCurrentText("pick")
    execute_btn = dlg._buttons.button(QDialogButtonBox.Ok)
    assert execute_btn.isEnabled() is True


def test_result_entries_returns_actions_and_oids(qtbot):
    commits = _commits()
    dlg = InteractiveRebaseDialog(commits, "main")
    qtbot.addWidget(dlg)
    # Change second to squash, third to drop
    dlg._table.cellWidget(1, 0).setCurrentText("squash")
    dlg._table.cellWidget(2, 0).setCurrentText("drop")
    result = dlg.result_entries()
    assert result == [
        ("pick", "aaa111"),
        ("squash", "bbb222"),
        ("drop", "ccc333"),
    ]
```

- [ ] **Step 2: Run — expect ImportError**

Run: `uv run pytest tests/presentation/dialogs/test_interactive_rebase_dialog.py -v`

- [ ] **Step 3: Implement the dialog**

Create `git_gui/presentation/dialogs/interactive_rebase_dialog.py`:

```python
"""Interactive rebase commit list editor dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from git_gui.domain.entities import Commit

_ACTIONS = ["pick", "squash", "fixup", "drop"]


class InteractiveRebaseDialog(QDialog):
    """Commit list editor for interactive rebase.

    Shows one row per commit (oldest-first). Each row has an action
    dropdown (pick/squash/fixup/drop), short oid, and first-line message.
    Rows are drag-and-drop reorderable.

    The "Execute" button is disabled when squash or fixup is on the
    first row (nothing to combine with).
    """

    def __init__(
        self,
        commits: list[Commit],
        target_label: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Interactive Rebase onto {target_label}")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        self._commits = list(commits)

        layout = QVBoxLayout(self)

        # Table
        self._table = QTableWidget(len(commits), 3)
        self._table.setHorizontalHeaderLabels(["Action", "OID", "Message"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.setColumnWidth(0, 100)
        self._table.setColumnWidth(1, 80)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)

        # Enable row drag-and-drop reorder
        self._table.setDragDropMode(QAbstractItemView.InternalMove)
        self._table.setDragDropOverwriteMode(False)

        for row, commit in enumerate(commits):
            # Action combo
            combo = QComboBox()
            combo.addItems(_ACTIONS)
            combo.setCurrentText("pick")
            combo.currentTextChanged.connect(self._validate)
            self._table.setCellWidget(row, 0, combo)

            # OID
            oid_item = QTableWidgetItem(commit.oid[:7])
            oid_item.setFlags(oid_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 1, oid_item)

            # Message (first line)
            msg_line = commit.message.split("\n", 1)[0]
            msg_item = QTableWidgetItem(msg_line)
            msg_item.setFlags(msg_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 2, msg_item)

        layout.addWidget(self._table)

        # Buttons
        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Execute")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._validate()

    def _validate(self) -> None:
        """Disable Execute when squash/fixup is on the first row."""
        execute_btn = self._buttons.button(QDialogButtonBox.Ok)
        if self._table.rowCount() == 0:
            execute_btn.setEnabled(False)
            return
        first_combo = self._table.cellWidget(0, 0)
        if first_combo and first_combo.currentText() in ("squash", "fixup"):
            execute_btn.setEnabled(False)
            execute_btn.setToolTip(
                "Cannot squash/fixup the first commit — no preceding commit to combine with."
            )
        else:
            execute_btn.setEnabled(True)
            execute_btn.setToolTip("")

    def result_entries(self) -> list[tuple[str, str]]:
        """Return (action, full_oid) tuples in current row order."""
        entries: list[tuple[str, str]] = []
        for row in range(self._table.rowCount()):
            combo = self._table.cellWidget(row, 0)
            action = combo.currentText() if combo else "pick"
            # Find the original commit by matching the short oid
            short_oid = self._table.item(row, 1).text()
            full_oid = short_oid  # fallback
            for c in self._commits:
                if c.oid[:7] == short_oid:
                    full_oid = c.oid
                    break
            entries.append((action, full_oid))
        return entries
```

- [ ] **Step 4: Run — expect all PASS**

Run: `uv run pytest tests/presentation/dialogs/test_interactive_rebase_dialog.py -v`

- [ ] **Step 5: Full suite**

Run: `uv run pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/dialogs/interactive_rebase_dialog.py tests/presentation/dialogs/test_interactive_rebase_dialog.py
git commit -m "feat(dialogs): create InteractiveRebaseDialog with action dropdowns and row reorder"
```

---

## Task 7: Add graph signals + context menu entries

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py`

- [ ] **Step 1: Add signals**

In `GraphWidget` class (around line 174-186, after existing signals), add:

```python
    interactive_rebase_branch_requested = Signal(str)   # branch name
    interactive_rebase_commit_requested = Signal(str)    # oid
```

- [ ] **Step 2: Add interactive rebase actions to the menu**

In `_add_merge_rebase_section`, after the rebase actions collection block (after the `rebase_actions` list is built, around line 663), add a new block that builds interactive rebase actions:

```python
        # Collect interactive rebase actions
        irebase_actions: list[tuple[str, str | None, object]] = []
        for b in branch_targets:
            irebase_actions.append((
                f"Interactive rebase onto {b}",
                None,
                lambda _checked=False, n=b: self.interactive_rebase_branch_requested.emit(n),
            ))
        if show_commit_rebase:
            irebase_actions.append((
                f"Interactive rebase onto commit {short_oid}",
                None,
                lambda _checked=False, o=oid: self.interactive_rebase_commit_requested.emit(o),
            ))
```

Then in the section where rebase actions are added to the menu (after the rebase submenu block), add:

```python
        # Add interactive rebase actions: submenu if ≥2, top-level if 1
        if len(irebase_actions) == 1:
            label, tooltip, emit = irebase_actions[0]
            _add(menu, label, tooltip, emit)
        elif irebase_actions:
            sub = menu.addMenu("Interactive Rebase")
            sub.setToolTipsVisible(True)
            for label, tooltip, emit in irebase_actions:
                _add(sub, label, tooltip, emit)
```

- [ ] **Step 3: Verify**

Run: `uv run python -c "from git_gui.presentation.widgets.graph import GraphWidget; print('ok')"`

- [ ] **Step 4: Full suite**

Run: `uv run pytest tests/ -x -q`

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/widgets/graph.py
git commit -m "feat(graph): add interactive rebase context menu entries"
```

---

## Task 8: Wire main_window handlers

**Files:**
- Modify: `git_gui/presentation/main_window.py`

- [ ] **Step 1: Add import**

In `main_window.py`, add:

```python
from git_gui.presentation.dialogs.interactive_rebase_dialog import InteractiveRebaseDialog
```

- [ ] **Step 2: Connect signals**

In the "Graph context menu signals" block (around line 157-160), add:

```python
        self._graph.interactive_rebase_branch_requested.connect(self._on_interactive_rebase_branch)
        self._graph.interactive_rebase_commit_requested.connect(self._on_interactive_rebase_commit)
```

- [ ] **Step 3: Add handlers**

Add these methods to `MainWindow`:

```python
    def _on_interactive_rebase_branch(self, branch: str) -> None:
        try:
            all_branches = self._queries.get_branches.execute()
            target = None
            for b in all_branches:
                if b.name == branch:
                    target = b
                    break
            if not target:
                self._log_panel.log_error(f"Branch not found: {branch}")
                return
            self._open_interactive_rebase(target.target_oid, branch)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Interactive rebase — ERROR: {e}")

    def _on_interactive_rebase_commit(self, oid: str) -> None:
        self._open_interactive_rebase(oid, f"commit {oid[:7]}")

    def _open_interactive_rebase(self, target_oid: str, target_label: str) -> None:
        try:
            head_oid = self._queries.get_head_oid.execute()
            if not head_oid:
                self._log_panel.log_error("No HEAD — cannot rebase")
                return
            commits = self._queries.get_commit_range.execute(head_oid, target_oid)
            if not commits:
                self._log_panel.log("No commits to rebase")
                return
            dlg = InteractiveRebaseDialog(commits, target_label, parent=self)
            if dlg.exec() != InteractiveRebaseDialog.Accepted:
                return
            entries = dlg.result_entries()
            self._run_remote_op(
                f"Interactive rebase onto {target_label}",
                lambda: self._commands.interactive_rebase.execute(target_oid, entries),
            )
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Interactive rebase — ERROR: {e}")
```

- [ ] **Step 4: Verify import**

Run: `uv run python -c "from git_gui.presentation.main_window import MainWindow; print('ok')"`

- [ ] **Step 5: Full suite**

Run: `uv run pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/main_window.py
git commit -m "feat(main_window): wire interactive rebase dialog flow"
```

---

## Task 9: Manual acceptance

- [ ] **Step 1: Launch the app**

Run: `uv run python main.py`

- [ ] **Step 2: Verify context menu**

Right-click a commit that has a branch → see "Interactive rebase onto {branch}" entry alongside the existing rebase entry. Click it.

- [ ] **Step 3: Verify the dialog**

- Table shows commits oldest-first with pick/squash/fixup/drop dropdowns.
- Rows can be dragged to reorder.
- Set first row to "squash" → Execute button disables.
- Change it back to "pick" → Execute re-enables.

- [ ] **Step 4: Execute a squash**

Create a test branch with 3 small commits. Open the interactive rebase dialog onto the branch base. Set the last two commits to "squash". Click Execute. Verify the graph shows 2 commits instead of 3, and the squashed commit contains all changes.

- [ ] **Step 5: Execute a drop**

Repeat with a "drop" action. Verify the dropped commit's changes are gone.

- [ ] **Step 6: Conflict during rebase**

Set up a conflict scenario (reorder commits that touch the same file). Click Execute. Verify the Spec C conflict banner appears. Resolve, continue, verify result.

- [ ] **Step 7: Commit any fixes**

If manual testing reveals issues, fix and commit with descriptive messages.

---

## Out of Scope

- Reword action (pause to edit commit message) — Phase 2
- Edit action (pause to amend) — Phase 2
- Autosquash (`--autosquash`) — follow-up
- `fixup -C` / `fixup -c` variants — follow-up
