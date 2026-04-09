# Branches Dialog and Checkout-Conflict Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `Git → Branches...` dialog for managing local branches (list with upstream, checkout, create, rename, delete, set/unset upstream) and a checkout-conflict prompt that resets a same-named local branch to a remote ref on confirmation.

**Architecture:** Clean architecture: domain entity → reader/writer ports → application command/query classes → bus → dialog. All branch operations use pygit2 directly. The checkout-conflict flow is wired into `MainWindow._on_checkout_branch`.

**Tech Stack:** Python 3, PySide6, pygit2, pytest, pytest-qt, `uv run`.

**Spec:** `docs/superpowers/specs/2026-04-09-branches-dialog-and-checkout-conflict-design.md`

---

## File Structure

**Created:**
- `git_gui/presentation/dialogs/branches_dialog.py` — `BranchesDialog` and helper modals.
- `tests/domain/test_entities_local_branch_info.py`
- `tests/application/test_queries_branches.py`
- `tests/application/test_commands_branches.py`
- `tests/infrastructure/test_pygit2_repo_branches.py`
- `tests/presentation/dialogs/test_branches_dialog.py`
- `tests/presentation/test_main_window_checkout_conflict.py`

**Modified:**
- `git_gui/domain/entities.py` — add `LocalBranchInfo` dataclass.
- `git_gui/domain/ports.py` — add reader and writer methods.
- `git_gui/application/queries.py` — add `ListLocalBranchesWithUpstream`.
- `git_gui/application/commands.py` — add `SetBranchUpstream`, `UnsetBranchUpstream`, `RenameBranch`, `ResetBranchToRef`.
- `git_gui/presentation/bus.py` — register the new query/commands.
- `git_gui/infrastructure/pygit2_repo.py` — implement the new methods.
- `git_gui/presentation/menus/git_menu.py` — add `&Branches...` action.
- `git_gui/presentation/main_window.py` — wrap `_on_checkout_branch` with conflict logic.

---

## Task 1: LocalBranchInfo entity

**Files:**
- Modify: `git_gui/domain/entities.py`
- Test: `tests/domain/test_entities_local_branch_info.py`

- [ ] **Step 1: Write the failing test**

```python
from git_gui.domain.entities import LocalBranchInfo


def test_local_branch_info_fields():
    b = LocalBranchInfo(
        name="master", upstream="origin/master",
        last_commit_sha="a1b2c3d", last_commit_message="fix: x",
    )
    assert b.name == "master"
    assert b.upstream == "origin/master"
    assert b.last_commit_sha == "a1b2c3d"
    assert b.last_commit_message == "fix: x"


def test_local_branch_info_upstream_optional():
    b = LocalBranchInfo(name="wip", upstream=None,
                        last_commit_sha="abc", last_commit_message="WIP")
    assert b.upstream is None
```

- [ ] **Step 2: Run** `uv run pytest tests/domain/test_entities_local_branch_info.py -v` — expect ImportError.

- [ ] **Step 3: Append to `git_gui/domain/entities.py`**

```python
@dataclass
class LocalBranchInfo:
    name: str
    upstream: str | None
    last_commit_sha: str
    last_commit_message: str
```

- [ ] **Step 4: Re-run** the test — expect 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add git_gui/domain/entities.py tests/domain/test_entities_local_branch_info.py
git commit -m "feat(domain): add LocalBranchInfo entity"
```

---

## Task 2: Extend ports

**Files:**
- Modify: `git_gui/domain/ports.py`

- [ ] **Step 1: Update entity import**

Add `LocalBranchInfo` (alphabetical) to the existing import line:

Current:
```python
from git_gui.domain.entities import Branch, Commit, CommitStat, FileStatus, Hunk, Remote, Stash, Submodule, Tag
```
New:
```python
from git_gui.domain.entities import Branch, Commit, CommitStat, FileStatus, Hunk, LocalBranchInfo, Remote, Stash, Submodule, Tag
```

- [ ] **Step 2: Add reader method**

In `IRepositoryReader`, add after `list_submodules`:
```python
    def list_local_branches_with_upstream(self) -> list[LocalBranchInfo]: ...
```

- [ ] **Step 3: Add writer methods**

In `IRepositoryWriter`, add after `set_submodule_url`:
```python
    def set_branch_upstream(self, name: str, upstream: str) -> None: ...
    def unset_branch_upstream(self, name: str) -> None: ...
    def rename_branch(self, old_name: str, new_name: str) -> None: ...
    def reset_branch_to_ref(self, branch: str, ref: str) -> None: ...
```

- [ ] **Step 4: Verify import**

Run: `uv run python -c "from git_gui.domain.ports import IRepositoryReader, IRepositoryWriter; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add git_gui/domain/ports.py
git commit -m "feat(domain): extend ports with branch management methods"
```

---

## Task 3: Application query class

**Files:**
- Modify: `git_gui/application/queries.py`
- Test: `tests/application/test_queries_branches.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import MagicMock
from git_gui.domain.entities import LocalBranchInfo
from git_gui.application.queries import ListLocalBranchesWithUpstream


def test_list_local_branches_with_upstream_calls_reader():
    reader = MagicMock()
    reader.list_local_branches_with_upstream.return_value = [
        LocalBranchInfo("master", "origin/master", "abc", "msg"),
    ]
    q = ListLocalBranchesWithUpstream(reader)
    result = q.execute()
    assert result == [LocalBranchInfo("master", "origin/master", "abc", "msg")]
    reader.list_local_branches_with_upstream.assert_called_once()
```

- [ ] **Step 2: Run** `uv run pytest tests/application/test_queries_branches.py -v` — expect ImportError.

- [ ] **Step 3: Update queries.py**

a) Add `LocalBranchInfo` to the entity import (alphabetical).

b) Append to `git_gui/application/queries.py`:
```python
class ListLocalBranchesWithUpstream:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> list[LocalBranchInfo]:
        return self._reader.list_local_branches_with_upstream()
```

- [ ] **Step 4: Re-run** — expect 1 PASSED.

- [ ] **Step 5: Commit**

```bash
git add git_gui/application/queries.py tests/application/test_queries_branches.py
git commit -m "feat(application): add ListLocalBranchesWithUpstream query"
```

---

## Task 4: Application command classes

**Files:**
- Modify: `git_gui/application/commands.py`
- Test: `tests/application/test_commands_branches.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import MagicMock
from git_gui.application.commands import (
    SetBranchUpstream, UnsetBranchUpstream, RenameBranch, ResetBranchToRef,
)


def test_set_branch_upstream():
    w = MagicMock()
    SetBranchUpstream(w).execute("feature", "origin/feature")
    w.set_branch_upstream.assert_called_once_with("feature", "origin/feature")


def test_unset_branch_upstream():
    w = MagicMock()
    UnsetBranchUpstream(w).execute("feature")
    w.unset_branch_upstream.assert_called_once_with("feature")


def test_rename_branch():
    w = MagicMock()
    RenameBranch(w).execute("old", "new")
    w.rename_branch.assert_called_once_with("old", "new")


def test_reset_branch_to_ref():
    w = MagicMock()
    ResetBranchToRef(w).execute("feature", "origin/feature")
    w.reset_branch_to_ref.assert_called_once_with("feature", "origin/feature")
```

- [ ] **Step 2: Run** `uv run pytest tests/application/test_commands_branches.py -v` — expect ImportError.

- [ ] **Step 3: Append to `git_gui/application/commands.py`**

```python
class SetBranchUpstream:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str, upstream: str) -> None:
        self._writer.set_branch_upstream(name, upstream)


class UnsetBranchUpstream:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str) -> None:
        self._writer.unset_branch_upstream(name)


class RenameBranch:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, old_name: str, new_name: str) -> None:
        self._writer.rename_branch(old_name, new_name)


class ResetBranchToRef:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, branch: str, ref: str) -> None:
        self._writer.reset_branch_to_ref(branch, ref)
```

- [ ] **Step 4: Re-run** — expect 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add git_gui/application/commands.py tests/application/test_commands_branches.py
git commit -m "feat(application): add branch management commands"
```

---

## Task 5: Wire buses

**Files:**
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Update queries import**

Append `ListLocalBranchesWithUpstream` to the queries import block:
```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes, GetTags, GetRemoteTags, GetCommitStats,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
    GetCommitDetail, IsDirty, GetHeadOid,
    ListRemotes, ListSubmodules,
    ListLocalBranchesWithUpstream,
)
```

- [ ] **Step 2: Update commands import**

Append `SetBranchUpstream, UnsetBranchUpstream, RenameBranch, ResetBranchToRef` to the existing commands import block (inside the `from ... import (` parens, after the submodule entries).

- [ ] **Step 3: Add fields to QueryBus**

In the `QueryBus` dataclass, append after `list_submodules`:
```python
    list_local_branches_with_upstream: ListLocalBranchesWithUpstream
```

In `QueryBus.from_reader`, append after `list_submodules=ListSubmodules(reader),`:
```python
            list_local_branches_with_upstream=ListLocalBranchesWithUpstream(reader),
```

- [ ] **Step 4: Add fields to CommandBus**

In `CommandBus` dataclass, append after `set_submodule_url`:
```python
    set_branch_upstream: SetBranchUpstream
    unset_branch_upstream: UnsetBranchUpstream
    rename_branch: RenameBranch
    reset_branch_to_ref: ResetBranchToRef
```

In `CommandBus.from_writer`, append after `set_submodule_url=SetSubmoduleUrl(writer),`:
```python
            set_branch_upstream=SetBranchUpstream(writer),
            unset_branch_upstream=UnsetBranchUpstream(writer),
            rename_branch=RenameBranch(writer),
            reset_branch_to_ref=ResetBranchToRef(writer),
```

- [ ] **Step 5: Verify**

```bash
uv run python -c "from git_gui.presentation.bus import QueryBus, CommandBus; from unittest.mock import MagicMock; QueryBus.from_reader(MagicMock()); CommandBus.from_writer(MagicMock()); print('ok')"
```
Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/bus.py
git commit -m "feat(bus): register branch management queries and commands"
```

---

## Task 6: Pygit2Repository — implement branch methods

**Files:**
- Modify: `git_gui/infrastructure/pygit2_repo.py`
- Test: `tests/infrastructure/test_pygit2_repo_branches.py`

- [ ] **Step 1: Write the failing test**

Create `tests/infrastructure/test_pygit2_repo_branches.py`:

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
    _run(str(p), "init", "-q", "-b", "master")
    _run(str(p), "config", "user.email", "t@t")
    _run(str(p), "config", "user.name", "t")
    (p / "f.txt").write_text("hi")
    _run(str(p), "add", ".")
    _run(str(p), "commit", "-q", "-m", "init")
    # Create a fake "remote" tracking ref by adding a remote pointing at self.
    _run(str(p), "remote", "add", "origin", str(p))
    _run(str(p), "fetch", "-q", "origin")
    return Pygit2Repository(str(p)), p


def test_list_local_branches_no_upstream(repo):
    r, _ = repo
    infos = r.list_local_branches_with_upstream()
    assert len(infos) == 1
    info = infos[0]
    assert info.name == "master"
    assert info.upstream is None
    assert len(info.last_commit_sha) >= 7
    assert info.last_commit_message == "init"


def test_set_and_list_upstream(repo):
    r, _ = repo
    r.set_branch_upstream("master", "origin/master")
    infos = r.list_local_branches_with_upstream()
    assert infos[0].upstream == "origin/master"


def test_unset_upstream(repo):
    r, _ = repo
    r.set_branch_upstream("master", "origin/master")
    r.unset_branch_upstream("master")
    assert r.list_local_branches_with_upstream()[0].upstream is None


def test_rename_branch(repo):
    r, p = repo
    _run(str(p), "branch", "feature")
    r.rename_branch("feature", "feature2")
    names = [i.name for i in r.list_local_branches_with_upstream()]
    assert "feature2" in names
    assert "feature" not in names


def test_reset_branch_to_ref(repo):
    r, p = repo
    # Create a second commit on master
    (p / "g.txt").write_text("g")
    _run(str(p), "add", ".")
    _run(str(p), "commit", "-q", "-m", "second")
    second_sha = r.list_local_branches_with_upstream()[0].last_commit_sha
    # Create a side branch from current HEAD, then add a third commit on master
    _run(str(p), "branch", "side")
    (p / "h.txt").write_text("h")
    _run(str(p), "add", ".")
    _run(str(p), "commit", "-q", "-m", "third")
    # Switch to side and reset side to master (which is now ahead by one)
    _run(str(p), "checkout", "-q", "side")
    r.reset_branch_to_ref("side", "master")
    side_info = next(i for i in r.list_local_branches_with_upstream() if i.name == "side")
    # side now points to master HEAD (third commit), which has a different sha
    assert side_info.last_commit_sha != second_sha
```

- [ ] **Step 2: Run** `uv run pytest tests/infrastructure/test_pygit2_repo_branches.py -v` — expect AttributeError.

- [ ] **Step 3: Update entity import in pygit2_repo.py**

Add `LocalBranchInfo` to the existing entities import (alphabetical).

- [ ] **Step 4: Add the methods**

Append at the end of the `Pygit2Repository` class:

```python
    # ----- Branch management -----

    def list_local_branches_with_upstream(self) -> list[LocalBranchInfo]:
        result: list[LocalBranchInfo] = []
        for name in self._repo.branches.local:
            br = self._repo.branches.local[name]
            try:
                upstream = br.upstream.shorthand if br.upstream else None
            except Exception:
                upstream = None
            commit = br.peel(pygit2.Commit)
            sha = str(commit.id)[:10]
            msg = commit.message.strip().split("\n", 1)[0]
            result.append(LocalBranchInfo(
                name=name,
                upstream=upstream,
                last_commit_sha=sha,
                last_commit_message=msg,
            ))
        return result

    def set_branch_upstream(self, name: str, upstream: str) -> None:
        local = self._repo.branches.local[name]
        remote = self._repo.branches.remote[upstream]
        local.upstream = remote

    def unset_branch_upstream(self, name: str) -> None:
        local = self._repo.branches.local[name]
        local.upstream = None

    def rename_branch(self, old_name: str, new_name: str) -> None:
        self._repo.branches.local[old_name].rename(new_name)

    def reset_branch_to_ref(self, branch: str, ref: str) -> None:
        # Resolves the target ref to an oid and hard-resets the working tree.
        # Caller is responsible for ensuring `branch` is the currently checked-
        # out branch (this method does not switch branches).
        target = self._repo.revparse_single(ref)
        oid = target.id if hasattr(target, "id") else target.target
        self._repo.reset(oid, pygit2.GIT_RESET_HARD)
```

- [ ] **Step 5: Re-run** — expect 5 PASSED.

- [ ] **Step 6: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_pygit2_repo_branches.py
git commit -m "feat(infra): implement branch management on Pygit2Repository"
```

---

## Task 7: BranchesDialog (presentation)

**Files:**
- Create: `git_gui/presentation/dialogs/branches_dialog.py`
- Test: `tests/presentation/dialogs/test_branches_dialog.py`

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/dialogs/test_branches_dialog.py`:

```python
from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Branch, LocalBranchInfo
from git_gui.presentation.dialogs.branches_dialog import BranchesDialog


@pytest.fixture
def buses():
    queries = MagicMock()
    commands = MagicMock()
    queries.list_local_branches_with_upstream.execute.return_value = [
        LocalBranchInfo("master", "origin/master", "abc1234567", "init"),
        LocalBranchInfo("wip", None, "def5678901", "WIP"),
    ]
    queries.get_branches.execute.return_value = [
        Branch("master", False, True, "abc"),
        Branch("wip", False, False, "def"),
        Branch("origin/master", True, False, "abc"),
    ]
    return queries, commands


def test_dialog_populates_table(qtbot, buses):
    queries, commands = buses
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    assert d._table.rowCount() == 2
    assert d._table.item(0, 0).text() == "master"
    assert d._table.item(0, 1).text() == "origin/master"
    assert d._table.item(1, 1).text() == "(none)"


def test_delete_calls_command(qtbot, buses):
    queries, commands = buses
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(1)  # wip
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        d._on_delete()
    commands.delete_branch.execute.assert_called_once_with("wip")


def test_rename_calls_command(qtbot, buses):
    queries, commands = buses
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(1)
    with patch(
        "git_gui.presentation.dialogs.branches_dialog._RenameDialog"
    ) as RD:
        instance = RD.return_value
        instance.exec.return_value = 1  # QDialog.Accepted
        instance.value.return_value = "wip2"
        d._on_rename()
    commands.rename_branch.execute.assert_called_once_with("wip", "wip2")


def test_set_upstream_calls_command(qtbot, buses):
    queries, commands = buses
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(1)
    with patch(
        "git_gui.presentation.dialogs.branches_dialog._UpstreamDialog"
    ) as UD:
        instance = UD.return_value
        instance.exec.return_value = 1
        instance.value.return_value = "origin/master"
        d._on_set_upstream()
    commands.set_branch_upstream.execute.assert_called_once_with("wip", "origin/master")


def test_set_upstream_none_calls_unset(qtbot, buses):
    queries, commands = buses
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(0)
    with patch(
        "git_gui.presentation.dialogs.branches_dialog._UpstreamDialog"
    ) as UD:
        instance = UD.return_value
        instance.exec.return_value = 1
        instance.value.return_value = None
        d._on_set_upstream()
    commands.unset_branch_upstream.execute.assert_called_once_with("master")


def test_error_shows_messagebox(qtbot, buses):
    queries, commands = buses
    commands.delete_branch.execute.side_effect = RuntimeError("boom")
    d = BranchesDialog(queries, commands)
    qtbot.addWidget(d)
    d._table.selectRow(1)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
         patch.object(QMessageBox, "warning") as warn:
        d._on_delete()
    warn.assert_called_once()
    assert "boom" in warn.call_args[0][2]
```

- [ ] **Step 2: Run** `uv run pytest tests/presentation/dialogs/test_branches_dialog.py -v` — expect ModuleNotFoundError.

- [ ] **Step 3: Implement the dialog**

Create `git_gui/presentation/dialogs/branches_dialog.py`:

```python
from __future__ import annotations
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)


class _CreateDialog(QDialog):
    def __init__(self, parent=None, default_start: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Branch")
        self._name = QLineEdit()
        self._start = QLineEdit(default_start)
        form = QFormLayout()
        form.addRow("Name:", self._name)
        form.addRow("Start point:", self._start)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self._name.text().strip(), self._start.text().strip()


class _RenameDialog(QDialog):
    def __init__(self, parent=None, current: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Rename Branch")
        self._name = QLineEdit(current)
        form = QFormLayout()
        form.addRow("New name:", self._name)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def value(self) -> str:
        return self._name.text().strip()


class _UpstreamDialog(QDialog):
    """Modal that lets the user pick a remote branch (or `(none)`).

    `value()` returns the chosen remote branch name, or `None` for `(none)`.
    """

    def __init__(self, parent=None, remote_branches: list[str] | None = None,
                 current: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Upstream")
        self._combo = QComboBox()
        self._combo.addItem("(none)")
        for rb in (remote_branches or []):
            self._combo.addItem(rb)
        if current:
            idx = self._combo.findText(current)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        form = QFormLayout()
        form.addRow("Upstream:", self._combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def value(self) -> str | None:
        text = self._combo.currentText()
        return None if text == "(none)" else text


class BranchesDialog(QDialog):
    def __init__(self, queries, commands, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Branches")
        self.resize(720, 420)
        self._queries = queries
        self._commands = commands

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Name", "Upstream", "Last commit"])
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)

        self._checkout_btn = QPushButton("Checkout")
        self._create_btn = QPushButton("Create...")
        self._rename_btn = QPushButton("Rename...")
        self._upstream_btn = QPushButton("Set Upstream...")
        self._delete_btn = QPushButton("Delete")
        self._close_btn = QPushButton("Close")

        self._checkout_btn.clicked.connect(self._on_checkout)
        self._create_btn.clicked.connect(self._on_create)
        self._rename_btn.clicked.connect(self._on_rename)
        self._upstream_btn.clicked.connect(self._on_set_upstream)
        self._delete_btn.clicked.connect(self._on_delete)
        self._close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._checkout_btn)
        btn_row.addWidget(self._create_btn)
        btn_row.addWidget(self._rename_btn)
        btn_row.addWidget(self._upstream_btn)
        btn_row.addWidget(self._delete_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addLayout(btn_row)

        self._refresh()

    def _refresh(self) -> None:
        try:
            infos = self._queries.list_local_branches_with_upstream.execute()
        except Exception as e:
            QMessageBox.warning(self, "Load branches failed", str(e))
            infos = []
        self._table.setRowCount(0)
        for info in infos:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(info.name))
            self._table.setItem(
                row, 1,
                QTableWidgetItem(info.upstream if info.upstream else "(none)"),
            )
            commit_text = f"{info.last_commit_sha}  {info.last_commit_message}"
            self._table.setItem(row, 2, QTableWidgetItem(commit_text))

    def _selected_name(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 0).text()

    def _selected_upstream(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        text = self._table.item(rows[0].row(), 1).text()
        return None if text == "(none)" else text

    def _remote_branch_names(self) -> list[str]:
        try:
            return [b.name for b in self._queries.get_branches.execute() if b.is_remote]
        except Exception:
            return []

    def _on_checkout(self) -> None:
        name = self._selected_name()
        if not name:
            return
        try:
            self._commands.checkout.execute(name)
        except Exception as e:
            QMessageBox.warning(self, "Checkout failed", str(e))
            return
        self.accept()

    def _on_create(self) -> None:
        default_start = self._selected_name() or ""
        d = _CreateDialog(self, default_start=default_start)
        if d.exec() != QDialog.Accepted:
            return
        name, start = d.values()
        if not name or not start:
            QMessageBox.warning(self, "Invalid input", "Name and start point are required.")
            return
        try:
            self._commands.create_branch.execute(name, start)
            self._commands.checkout.execute(name)
        except Exception as e:
            QMessageBox.warning(self, "Create branch failed", str(e))
        self._refresh()

    def _on_rename(self) -> None:
        old = self._selected_name()
        if not old:
            return
        d = _RenameDialog(self, current=old)
        if d.exec() != QDialog.Accepted:
            return
        new = d.value()
        if not new or new == old:
            return
        try:
            self._commands.rename_branch.execute(old, new)
        except Exception as e:
            QMessageBox.warning(self, "Rename branch failed", str(e))
        self._refresh()

    def _on_set_upstream(self) -> None:
        name = self._selected_name()
        if not name:
            return
        d = _UpstreamDialog(
            self,
            remote_branches=self._remote_branch_names(),
            current=self._selected_upstream(),
        )
        if d.exec() != QDialog.Accepted:
            return
        new_upstream = d.value()
        try:
            if new_upstream is None:
                self._commands.unset_branch_upstream.execute(name)
            else:
                self._commands.set_branch_upstream.execute(name, new_upstream)
        except Exception as e:
            QMessageBox.warning(self, "Set upstream failed", str(e))
        self._refresh()

    def _on_delete(self) -> None:
        name = self._selected_name()
        if not name:
            return
        if QMessageBox.question(self, "Delete branch", f"Delete branch '{name}'?") != QMessageBox.Yes:
            return
        try:
            self._commands.delete_branch.execute(name)
        except Exception as e:
            QMessageBox.warning(self, "Delete branch failed", str(e))
        self._refresh()
```

- [ ] **Step 4: Re-run** — expect 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/dialogs/branches_dialog.py tests/presentation/dialogs/test_branches_dialog.py
git commit -m "feat(presentation): add BranchesDialog"
```

---

## Task 8: Wire Branches dialog into the Git menu

**Files:**
- Modify: `git_gui/presentation/menus/git_menu.py`

- [ ] **Step 1: Add import**

In `git_gui/presentation/menus/git_menu.py`, add:
```python
from git_gui.presentation.dialogs.branches_dialog import BranchesDialog
```

- [ ] **Step 2: Add the action**

Inside `install_git_menu`, after the `remote_action` block and BEFORE the `submodule_action` block, add:

```python
    branches_action = QAction("&Branches...", window)

    def _open_branches() -> None:
        if queries is None or commands is None:
            return
        BranchesDialog(queries, commands, window).exec()

    branches_action.triggered.connect(_open_branches)
```

And after `git_menu.addAction(remote_action)`, before `git_menu.addAction(submodule_action)`, add:
```python
    git_menu.addAction(branches_action)
```

Also add (next to the other action holds):
```python
    window._git_branches_action = branches_action  # type: ignore[attr-defined]
```

- [ ] **Step 3: Smoke test**

Run: `uv run python -c "from git_gui.presentation.menus.git_menu import install_git_menu; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Run the existing git_menu test**

Run: `uv run pytest tests/presentation/menus/test_git_menu.py -v`
Expected: still passing (the existing test only asserts that `&Remotes...` and `&Submodules...` exist, so adding a third action doesn't break it).

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/menus/git_menu.py
git commit -m "feat(menu): add Branches action to Git menu"
```

---

## Task 9: MainWindow checkout-conflict logic

**Files:**
- Modify: `git_gui/presentation/main_window.py`
- Test: `tests/presentation/test_main_window_checkout_conflict.py`

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/test_main_window_checkout_conflict.py`:

```python
from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Branch
from git_gui.presentation.main_window import MainWindow


def _make_window(qtbot):
    repo_store = MagicMock()
    repo_store.get_open_repos.return_value = []
    repo_store.get_recent_repos.return_value = []
    repo_store.get_active.return_value = None
    win = MainWindow(queries=None, commands=None, repo_store=repo_store)
    qtbot.addWidget(win)
    return win


def _wire_buses(win):
    queries = MagicMock()
    commands = MagicMock()
    queries.get_branches.execute.return_value = [
        Branch("feature", False, False, "abc"),
        Branch("origin/feature", True, False, "abc"),
    ]
    win._queries = queries
    win._commands = commands
    return queries, commands


def test_conflict_yes_resets_local(qtbot):
    win = _make_window(qtbot)
    queries, commands = _wire_buses(win)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
         patch.object(win, "_reload"):
        win._on_checkout_branch("origin/feature")
    commands.checkout.execute.assert_called_once_with("feature")
    commands.reset_branch_to_ref.execute.assert_called_once_with(
        "feature", "origin/feature"
    )


def test_conflict_cancel_does_nothing(qtbot):
    win = _make_window(qtbot)
    queries, commands = _wire_buses(win)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel), \
         patch.object(win, "_reload"):
        win._on_checkout_branch("origin/feature")
    commands.checkout.execute.assert_not_called()
    commands.reset_branch_to_ref.execute.assert_not_called()
    commands.checkout_remote_branch.execute.assert_not_called()


def test_no_conflict_falls_through(qtbot):
    win = _make_window(qtbot)
    queries, commands = _wire_buses(win)
    queries.get_branches.execute.return_value = [
        Branch("origin/feature", True, False, "abc"),
    ]
    with patch.object(win, "_reload"):
        win._on_checkout_branch("origin/feature")
    commands.checkout_remote_branch.execute.assert_called_once_with("origin/feature")
```

- [ ] **Step 2: Run** `uv run pytest tests/presentation/test_main_window_checkout_conflict.py -v` — expect failures (existing `_on_checkout_branch` doesn't handle the conflict path).

- [ ] **Step 3: Update `_on_checkout_branch` in `git_gui/presentation/main_window.py`**

Replace the existing method with:

```python
    def _on_checkout_branch(self, name: str) -> None:
        try:
            if "/" in name:
                # Remote branch — check for same-named local
                local_name = name.split("/", 1)[1]
                existing = {
                    b.name for b in self._queries.get_branches.execute()
                    if not b.is_remote
                }
                if local_name in existing:
                    reply = QMessageBox.question(
                        self,
                        "Local branch exists",
                        f"Local branch '{local_name}' already exists.\n\n"
                        f"Reset it to '{name}' (HEAD)? This discards any local "
                        f"commits and uncommitted changes on '{local_name}'.",
                        QMessageBox.Yes | QMessageBox.Cancel,
                        QMessageBox.Cancel,
                    )
                    if reply != QMessageBox.Yes:
                        return
                    self._commands.checkout.execute(local_name)
                    self._commands.reset_branch_to_ref.execute(local_name, name)
                    self._log_panel.log(f"Reset {local_name} to {name}")
                else:
                    self._commands.checkout_remote_branch.execute(name)
                    self._log_panel.log(f"Checkout remote: {name} → local {local_name}")
            else:
                self._commands.checkout.execute(name)
                self._log_panel.log(f"Checkout branch: {name}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Checkout {name} — ERROR: {e}")
        self._reload()
```

- [ ] **Step 4: Re-run** — expect 3 PASSED.

- [ ] **Step 5: Run the full suite to catch regressions**

Run: `uv run pytest tests/ -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/main_window.py tests/presentation/test_main_window_checkout_conflict.py
git commit -m "feat(main-window): prompt to reset same-named local branch on remote checkout"
```

---

## Final Verification

- [ ] **Run full test suite once more**

Run: `uv run pytest tests/ -v`
Expected: all green.

- [ ] **Manual smoke test**

Launch the app: `uv run python main.py`. Open a repo with multiple local branches. Verify:
1. `Git → Branches...` opens, shows local branches with upstream and last commit.
2. Checkout, Create, Rename, Set Upstream (`(none)` and a real remote branch), Delete all work.
3. Errors show a `QMessageBox.warning` and the dialog stays open.
4. From the graph context menu, "Checkout branch" → pick a remote branch whose local exists. Verify the conflict dialog appears, Yes resets the local, Cancel does nothing.
5. Same flow with a remote branch whose local does NOT exist — verify it falls through to the standard remote-checkout flow with no prompt.

---

## Notes for the implementer

- All Python operations run via `uv run` per `CLAUDE.md`.
- Tests at `tests/infrastructure/` use real `git` CLI; ensure git is on PATH.
- Do NOT add ahead/behind columns, HEAD-marker columns, multi-select, or force-delete — explicitly out of scope.
- Do NOT thread anything; branch ops are fast and synchronous.
- The conflict path uses `checkout` + `reset_branch_to_ref` (two ops) instead of one combined op so `reset_branch_to_ref` stays a generic writer method.
