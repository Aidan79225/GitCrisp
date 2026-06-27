# Batch-delete Remote Branches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Remote Branches" dialog that lets users batch-delete remote branches in a few clicks.

**Architecture:** Clean Architecture. A new domain result type + two port methods; pygit2/subprocess implementations (a porcelain-push deleter and a default-branch resolver); application command/query wrappers registered on the buses; a new modal dialog opened from the Git menu that groups selections by remote and deletes them on a background thread.

**Tech Stack:** Python 3.13, pygit2, `git` subprocess, PySide6 (Qt Widgets), pytest + pytest-qt, `uv`.

## Global Constraints

- Run all Python via `uv run` (e.g. `uv run pytest`, never bare `pytest`).
- Clean Architecture: dependencies point inward (presentation → application → domain ← infrastructure). Never import presentation/infrastructure from domain/application.
- All widget colors come from theme tokens; no hard-coded hex in widget code.
- `ruff check .` and `ruff format --check .` must pass.
- Commit after each task (frequent commits). Branch: `feat/batch-delete-remote-branches` (already created).

---

### Task 1: Domain — `RemoteBranchDeleteResult` + port signatures

**Files:**
- Modify: `git_gui/domain/entities.py`
- Modify: `git_gui/domain/ports.py`
- Test: `tests/domain/test_entities.py` (create if missing)

**Interfaces:**
- Produces: `RemoteBranchDeleteResult(branch: str, ok: bool, message: str)` dataclass;
  `IRepositoryReader.remote_default_branches() -> dict[str, str]`;
  `IRepositoryWriter.delete_remote_branches(remote: str, branches: list[str]) -> list[RemoteBranchDeleteResult]`.

- [ ] **Step 1: Write the failing test**

Create/append `tests/domain/test_entities.py`:

```python
from git_gui.domain.entities import RemoteBranchDeleteResult


def test_remote_branch_delete_result_fields():
    r = RemoteBranchDeleteResult(branch="origin/feature", ok=False, message="rejected")
    assert r.branch == "origin/feature"
    assert r.ok is False
    assert r.message == "rejected"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_entities.py -v`
Expected: FAIL with `ImportError: cannot import name 'RemoteBranchDeleteResult'`.

- [ ] **Step 3: Add the dataclass**

In `git_gui/domain/entities.py`, after the `Branch` dataclass (around line 26), add:

```python
@dataclass
class RemoteBranchDeleteResult:
    branch: str  # full shorthand, e.g. "origin/feature-a"
    ok: bool
    message: str
```

- [ ] **Step 4: Add the port signatures**

In `git_gui/domain/ports.py`, inside `IRepositoryReader` (after `find_worktree_for_branch`, line 72) add:

```python
    def remote_default_branches(self) -> dict[str, str]: ...
```

Inside `IRepositoryWriter` (after `delete_remote_branch`, line 112) add:

```python
    def delete_remote_branches(
        self, remote: str, branches: list[str]
    ) -> list[RemoteBranchDeleteResult]: ...
```

Ensure `RemoteBranchDeleteResult` is imported in `ports.py` (it imports from `entities` already — add the name to that import).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/domain/test_entities.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add git_gui/domain/entities.py git_gui/domain/ports.py tests/domain/test_entities.py
git commit -m "feat(domain): RemoteBranchDeleteResult + batch remote-delete ports"
```

---

### Task 2: Infrastructure — porcelain parser

**Files:**
- Modify: `git_gui/infrastructure/pygit2/remote_ops.py`
- Test: `tests/infrastructure/test_remote_delete_parse.py` (create)

**Interfaces:**
- Consumes: `RemoteBranchDeleteResult` (Task 1).
- Produces: module-level `_parse_porcelain_delete(remote: str, stdout: str, branches: list[str]) -> list[RemoteBranchDeleteResult]`.

- [ ] **Step 1: Write the failing test**

Create `tests/infrastructure/test_remote_delete_parse.py`:

```python
from git_gui.infrastructure.pygit2.remote_ops import _parse_porcelain_delete


def test_all_deleted_ok():
    stdout = (
        "To github.com:u/r.git\n"
        "-\t:refs/heads/feat-a\t[deleted]\n"
        "-\t:refs/heads/feat-b\t[deleted]\n"
        "Done\n"
    )
    results = _parse_porcelain_delete("origin", stdout, ["feat-a", "feat-b"])
    assert [(r.branch, r.ok) for r in results] == [
        ("origin/feat-a", True),
        ("origin/feat-b", True),
    ]


def test_mixed_ok_and_rejected():
    stdout = (
        "To github.com:u/r.git\n"
        "-\t:refs/heads/feat-a\t[deleted]\n"
        "!\trefs/heads/protected:\t[remote rejected] (protected branch)\n"
        "Done\n"
    )
    results = _parse_porcelain_delete("origin", stdout, ["feat-a", "protected"])
    by = {r.branch: r for r in results}
    assert by["origin/feat-a"].ok is True
    assert by["origin/protected"].ok is False
    assert "rejected" in by["origin/protected"].message


def test_missing_line_marks_failed():
    results = _parse_porcelain_delete("origin", "", ["gone"])
    assert results[0].branch == "origin/gone"
    assert results[0].ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_remote_delete_parse.py -v`
Expected: FAIL with `ImportError: cannot import name '_parse_porcelain_delete'`.

- [ ] **Step 3: Implement the parser**

In `git_gui/infrastructure/pygit2/remote_ops.py`, add the import at the top (near the other imports):

```python
from git_gui.domain.entities import RemoteBranchDeleteResult
```

Add this module-level function (below the imports, above the class):

```python
def _parse_porcelain_delete(
    remote: str, stdout: str, branches: list[str]
) -> list[RemoteBranchDeleteResult]:
    """Parse `git push --porcelain ... --delete` output into per-branch results.

    Porcelain ref lines are tab-separated: `<flag>\\t<from>:<to>\\t<summary>`.
    For a delete the `<to>` ref identifies the branch; flag "-" means deleted,
    "!" means rejected (summary carries the reason).
    """
    status: dict[str, tuple[bool, str]] = {}
    for line in stdout.splitlines():
        if "\t" not in line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        flag, refpair, summary = parts[0], parts[1], parts[2]
        if ":" not in refpair:
            continue
        _from, to_ref = refpair.split(":", 1)
        to_ref = to_ref.strip()
        if not to_ref:
            continue
        short = to_ref
        if short.startswith("refs/heads/"):
            short = short[len("refs/heads/") :]
        ok = flag.strip() == "-"
        status[short] = (ok, "deleted" if ok else summary.strip())

    results: list[RemoteBranchDeleteResult] = []
    for b in branches:
        ok, msg = status.get(b, (False, "no result reported by git"))
        results.append(RemoteBranchDeleteResult(branch=f"{remote}/{b}", ok=ok, message=msg))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/infrastructure/test_remote_delete_parse.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/pygit2/remote_ops.py tests/infrastructure/test_remote_delete_parse.py
git commit -m "feat(infra): porcelain push-delete parser"
```

---

### Task 3: Infrastructure — `delete_remote_branches` writer

**Files:**
- Modify: `git_gui/infrastructure/pygit2/remote_ops.py`
- Test: `tests/infrastructure/test_remote_delete_writer.py` (create)

**Interfaces:**
- Consumes: `_parse_porcelain_delete` (Task 2).
- Produces: `RemoteOps.delete_remote_branches(remote: str, branches: list[str]) -> list[RemoteBranchDeleteResult]`.

Note: `RemoteOps` already imports `subprocess` and `subprocess_kwargs`, and exposes `self._repo.workdir` and `self._git_env` (used by `_run_git`).

- [ ] **Step 1: Write the failing test**

Create `tests/infrastructure/test_remote_delete_writer.py`:

```python
import subprocess
from types import SimpleNamespace

from git_gui.infrastructure.pygit2 import remote_ops


class _FakeRepo:
    workdir = "/tmp/repo"


def _make_ops():
    ops = remote_ops.RemoteOps.__new__(remote_ops.RemoteOps)
    ops._repo = _FakeRepo()
    ops._git_env = {}
    return ops


def test_delete_remote_branches_parses_push(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return SimpleNamespace(
            returncode=0,
            stdout="To x\n-\t:refs/heads/a\t[deleted]\n-\t:refs/heads/b\t[deleted]\nDone\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops = _make_ops()
    results = ops.delete_remote_branches("origin", ["a", "b"])
    assert [r.ok for r in results] == [True, True]
    assert captured["args"][:4] == ["git", "push", "--porcelain", "origin"]
    assert "--delete" in captured["args"]
    assert "refs/heads/a" in captured["args"]


def test_delete_remote_branches_total_failure_uses_stderr(monkeypatch):
    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=128, stdout="", stderr="fatal: could not read from remote")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops = _make_ops()
    results = ops.delete_remote_branches("origin", ["a"])
    assert results[0].ok is False
    assert "could not read" in results[0].message


def test_delete_remote_branches_empty_is_noop(monkeypatch):
    def fail(*a, **k):  # must not be called
        raise AssertionError("subprocess.run should not run for empty branches")

    monkeypatch.setattr(subprocess, "run", fail)
    ops = _make_ops()
    assert ops.delete_remote_branches("origin", []) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_remote_delete_writer.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'delete_remote_branches'`.

- [ ] **Step 3: Implement the writer**

In `git_gui/infrastructure/pygit2/remote_ops.py`, add this method to the `RemoteOps` class (next to `_run_git`):

```python
    def delete_remote_branches(
        self, remote: str, branches: list[str]
    ) -> list[RemoteBranchDeleteResult]:
        if not branches:
            return []
        refspecs = [f"refs/heads/{b}" for b in branches]
        result = subprocess.run(
            ["git", "push", "--porcelain", remote, "--delete", *refspecs],
            cwd=self._repo.workdir,
            capture_output=True,
            text=True,
            env=self._git_env,
            **subprocess_kwargs(),
        )
        parsed = _parse_porcelain_delete(remote, result.stdout, branches)
        # No per-ref status at all (e.g. couldn't reach the remote): surface stderr.
        if result.returncode != 0 and not result.stdout.strip():
            err = result.stderr.strip() or f"git exited {result.returncode}"
            return [
                RemoteBranchDeleteResult(branch=f"{remote}/{b}", ok=False, message=err)
                for b in branches
            ]
        return parsed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/infrastructure/test_remote_delete_writer.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/pygit2/remote_ops.py tests/infrastructure/test_remote_delete_writer.py
git commit -m "feat(infra): delete_remote_branches via batched porcelain push"
```

---

### Task 4: Infrastructure — `remote_default_branches` reader

**Files:**
- Modify: `git_gui/infrastructure/pygit2/branch_ops.py`
- Test: `tests/infrastructure/test_remote_default_branches.py` (create)

**Interfaces:**
- Produces: `BranchOps.remote_default_branches() -> dict[str, str]` (remote name → default shorthand).

`branch_ops.py` already has a module `logger`. The `writable_repo` fixture (a `Pygit2Repository` composite + repo Path, with one commit) lives in `tests/infrastructure/test_writes.py`; redefine the same small fixture here.

- [ ] **Step 1: Write the failing test**

Create `tests/infrastructure/test_remote_default_branches.py`:

```python
from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


@pytest.fixture
def writable_repo(repo_path) -> tuple[Pygit2Repository, Path]:
    return Pygit2Repository(str(repo_path)), repo_path


def test_remote_default_branches_resolves_symref(writable_repo):
    impl, path = writable_repo
    raw = pygit2.Repository(str(path))
    head_oid = raw.head.target
    raw.remotes.create("origin", "https://example.test/r.git")
    raw.references.create("refs/remotes/origin/main", head_oid)
    raw.references.create("refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    assert impl.remote_default_branches() == {"origin": "origin/main"}


def test_remote_default_branches_skips_remote_without_head(writable_repo):
    impl, path = writable_repo
    raw = pygit2.Repository(str(path))
    raw.remotes.create("origin", "https://example.test/r.git")
    raw.references.create("refs/remotes/origin/main", raw.head.target)
    # No refs/remotes/origin/HEAD symref created.

    assert impl.remote_default_branches() == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_remote_default_branches.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'remote_default_branches'`.

- [ ] **Step 3: Implement the reader**

In `git_gui/infrastructure/pygit2/branch_ops.py`, add this method to the class (after `get_branches`):

```python
    def remote_default_branches(self) -> dict[str, str]:
        """Map each remote to its default branch shorthand (e.g. "origin/main").

        Resolved from the `refs/remotes/<remote>/HEAD` symbolic ref. Remotes
        without a resolvable HEAD symref are omitted.
        """
        result: dict[str, str] = {}
        prefix = "refs/remotes/"
        for remote in self._repo.remotes:
            ref_name = f"{prefix}{remote.name}/HEAD"
            try:
                ref = self._repo.references.get(ref_name)
            except Exception as e:
                logger.warning("Failed to read %s: %s", ref_name, e)
                continue
            if ref is None:
                continue
            target = ref.target
            if isinstance(target, str) and target.startswith(prefix):
                result[remote.name] = target[len(prefix) :]
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/infrastructure/test_remote_default_branches.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/pygit2/branch_ops.py tests/infrastructure/test_remote_default_branches.py
git commit -m "feat(infra): remote_default_branches resolver"
```

---

### Task 5: Application — command + query + bus wiring

**Files:**
- Modify: `git_gui/application/commands.py`
- Modify: `git_gui/application/queries.py`
- Modify: `git_gui/presentation/bus.py`
- Test: `tests/application/test_commands.py`, `tests/application/test_queries.py`

**Interfaces:**
- Consumes: writer `delete_remote_branches` (Task 3), reader `remote_default_branches` (Task 4).
- Produces: `DeleteRemoteBranches.execute(remote, branches) -> list[RemoteBranchDeleteResult]`;
  `RemoteDefaultBranches.execute() -> dict[str, str]`; both registered on `CommandBus`/`QueryBus` as
  `commands.delete_remote_branches` and `queries.remote_default_branches`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/application/test_commands.py`:

```python
def test_delete_remote_branches_delegates():
    from unittest.mock import MagicMock

    from git_gui.application.commands import DeleteRemoteBranches

    w = MagicMock()
    w.delete_remote_branches.return_value = ["result"]
    cmd = DeleteRemoteBranches(w)
    out = cmd.execute("origin", ["a", "b"])
    w.delete_remote_branches.assert_called_once_with("origin", ["a", "b"])
    assert out == ["result"]
```

Append to `tests/application/test_queries.py`:

```python
def test_remote_default_branches_delegates():
    from unittest.mock import MagicMock

    from git_gui.application.queries import RemoteDefaultBranches

    r = MagicMock()
    r.remote_default_branches.return_value = {"origin": "origin/main"}
    q = RemoteDefaultBranches(r)
    assert q.execute() == {"origin": "origin/main"}
    r.remote_default_branches.assert_called_once_with()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/application/test_commands.py::test_delete_remote_branches_delegates tests/application/test_queries.py::test_remote_default_branches_delegates -v`
Expected: FAIL with `ImportError` for `DeleteRemoteBranches` / `RemoteDefaultBranches`.

- [ ] **Step 3: Implement the command**

In `git_gui/application/commands.py`, after `DeleteRemoteBranch` (line 108), add:

```python
class DeleteRemoteBranches:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, remote: str, branches: list[str]):
        return self._writer.delete_remote_branches(remote, branches)
```

- [ ] **Step 4: Implement the query**

In `git_gui/application/queries.py`, after `FindWorktreeForBranch` (line 271), add:

```python
class RemoteDefaultBranches:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> dict[str, str]:
        return self._reader.remote_default_branches()
```

- [ ] **Step 5: Register on the buses**

In `git_gui/presentation/bus.py`:

1. Add `DeleteRemoteBranches` to the `from git_gui.application.commands import (` block (keep alphabetical-ish, next to `DeleteRemoteBranch`).
2. Add `RemoteDefaultBranches` to the `from git_gui.application.queries import (` block.
3. In `class QueryBus`, after `find_worktree_for_branch: FindWorktreeForBranch` (line 129) add:

```python
    remote_default_branches: RemoteDefaultBranches
```

4. In `QueryBus.from_reader`, after `find_worktree_for_branch=FindWorktreeForBranch(reader),` (line 162) add:

```python
            remote_default_branches=RemoteDefaultBranches(reader),
```

5. In `class CommandBus`, after `delete_remote_branch: DeleteRemoteBranch` (line 176) add:

```python
    delete_remote_branches: DeleteRemoteBranches
```

6. In `CommandBus.from_writer`, after `delete_remote_branch=DeleteRemoteBranch(writer),` (line 237) add:

```python
            delete_remote_branches=DeleteRemoteBranches(writer),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/application/ -v`
Expected: PASS (including the two new tests). Also run `uv run pytest tests/presentation/test_main_window_session_factory.py -q` to confirm the buses still build.

- [ ] **Step 7: Commit**

```bash
git add git_gui/application/commands.py git_gui/application/queries.py git_gui/presentation/bus.py tests/application/test_commands.py tests/application/test_queries.py
git commit -m "feat(app): DeleteRemoteBranches command + RemoteDefaultBranches query"
```

---

### Task 6: Presentation — `RemoteBranchesDialog`

**Files:**
- Create: `git_gui/presentation/dialogs/remote_branches_dialog.py`
- Test: `tests/presentation/dialogs/test_remote_branches_dialog.py`

**Interfaces:**
- Consumes: `queries.get_branches`, `queries.remote_default_branches`, `commands.delete_remote_branches`.
- Produces: `RemoteBranchesDialog(queries, commands, parent=None)` with testable methods
  `_collect_selected() -> list[str]`, `_grouped_by_remote(names) -> dict[str, list[str]]`,
  `_perform_deletions(grouped) -> list[RemoteBranchDeleteResult]`, `_on_delete()`,
  `_on_delete_finished(results)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/presentation/dialogs/test_remote_branches_dialog.py`:

```python
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from git_gui.domain.entities import Branch, RemoteBranchDeleteResult
from git_gui.presentation.dialogs.remote_branches_dialog import RemoteBranchesDialog


def _make(qtbot, branches=None, defaults=None):
    queries = MagicMock()
    commands = MagicMock()
    queries.get_branches.execute.return_value = branches or [
        Branch("origin/feature-a", True, False, "a"),
        Branch("origin/feature-b", True, False, "b"),
        Branch("origin/main", True, False, "c"),
        Branch("origin/HEAD", True, False, "c"),
        Branch("local", False, True, "d"),
    ]
    queries.remote_default_branches.execute.return_value = defaults or {"origin": "origin/main"}
    dlg = RemoteBranchesDialog(queries, commands)
    qtbot.addWidget(dlg)
    return dlg, queries, commands


def _rows_by_name(dlg):
    out = {}
    for row in range(dlg._table.rowCount()):
        item = dlg._table.item(row, 0)
        out[item.data(Qt.UserRole)] = item
    return out


def test_lists_remote_branches_excluding_head(qtbot):
    dlg, _, _ = _make(qtbot)
    names = set(_rows_by_name(dlg))
    assert names == {"origin/feature-a", "origin/feature-b", "origin/main"}


def test_default_branch_not_checkable(qtbot):
    dlg, _, _ = _make(qtbot)
    rows = _rows_by_name(dlg)
    assert not (rows["origin/main"].flags() & Qt.ItemIsUserCheckable)
    assert rows["origin/feature-a"].flags() & Qt.ItemIsUserCheckable


def test_select_all_skips_default_and_counts(qtbot):
    dlg, _, _ = _make(qtbot)
    dlg._select_all_visible()
    assert set(dlg._collect_selected()) == {"origin/feature-a", "origin/feature-b"}
    assert dlg._delete_btn.text() == "Delete Selected (2)"


def test_filter_hides_non_matching(qtbot):
    dlg, _, _ = _make(qtbot)
    dlg._apply_filter("feature-a")
    rows = _rows_by_name(dlg)
    hidden = {n: dlg._table.isRowHidden(r) for r in range(dlg._table.rowCount())
              for n in [dlg._table.item(r, 0).data(Qt.UserRole)]}
    assert hidden["origin/feature-a"] is False
    assert hidden["origin/feature-b"] is True


def test_grouped_by_remote():
    grouped = RemoteBranchesDialog._grouped_by_remote(
        ["origin/a", "origin/b", "upstream/c"]
    )
    assert grouped == {"origin": ["a", "b"], "upstream": ["c"]}


def test_perform_deletions_one_call_per_remote(qtbot):
    dlg, _, commands = _make(qtbot)
    commands.delete_remote_branches.execute.side_effect = lambda remote, br: [
        RemoteBranchDeleteResult(f"{remote}/{b}", True, "deleted") for b in br
    ]
    results = dlg._perform_deletions({"origin": ["a", "b"], "upstream": ["c"]})
    assert commands.delete_remote_branches.execute.call_count == 2
    assert {r.branch for r in results} == {"origin/a", "origin/b", "upstream/c"}


def test_on_delete_cancel_does_nothing(qtbot):
    dlg, _, commands = _make(qtbot)
    dlg._select_all_visible()
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel):
        dlg._on_delete()
    commands.delete_remote_branches.execute.assert_not_called()


def test_on_delete_confirm_runs_and_refreshes(qtbot):
    dlg, queries, commands = _make(qtbot)
    commands.delete_remote_branches.execute.side_effect = lambda remote, br: [
        RemoteBranchDeleteResult(f"{remote}/{b}", True, "deleted") for b in br
    ]
    dlg._select_all_visible()

    class _SyncThread:
        def __init__(self, target=None, daemon=None):
            self._t = target

        def start(self):
            self._t()

    with (
        patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        patch.object(QMessageBox, "information"),
        patch("git_gui.presentation.dialogs.remote_branches_dialog.threading.Thread", _SyncThread),
    ):
        dlg._on_delete()

    assert commands.delete_remote_branches.execute.call_count == 1
    # refresh re-queried branches (called twice: initial + after delete)
    assert queries.get_branches.execute.call_count >= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/presentation/dialogs/test_remote_branches_dialog.py -v`
Expected: FAIL with `ModuleNotFoundError: ... remote_branches_dialog`.

- [ ] **Step 3: Implement the dialog**

Create `git_gui/presentation/dialogs/remote_branches_dialog.py`:

```python
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from git_gui.domain.entities import RemoteBranchDeleteResult

_MAX_LISTED_IN_CONFIRM = 15


class _DeleteSignals(QObject):
    finished = Signal(list)  # list[RemoteBranchDeleteResult]
    failed = Signal(str)


class RemoteBranchesDialog(QDialog):
    def __init__(self, queries, commands, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remote Branches")
        self.resize(560, 480)
        self._queries = queries
        self._commands = commands
        self._defaults: set[str] = set()
        self._signals: _DeleteSignals | None = None

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter…")
        self._filter.textChanged.connect(self._apply_filter)

        self._table = QTableWidget(0, 1)
        self._table.setHorizontalHeaderLabels(["Remote branch"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.itemChanged.connect(self._on_item_changed)

        self._select_all_btn = QPushButton("Select All")
        self._clear_btn = QPushButton("Clear")
        self._delete_btn = QPushButton("Delete Selected (0)")
        self._close_btn = QPushButton("Close")
        self._select_all_btn.clicked.connect(self._select_all_visible)
        self._clear_btn.clicked.connect(self._clear_all)
        self._delete_btn.clicked.connect(self._on_delete)
        self._close_btn.clicked.connect(self.accept)

        top = QHBoxLayout()
        top.addWidget(QLabel("Filter:"))
        top.addWidget(self._filter, 1)
        top.addWidget(self._select_all_btn)
        top.addWidget(self._clear_btn)

        bottom = QHBoxLayout()
        bottom.addWidget(self._delete_btn)
        bottom.addStretch(1)
        bottom.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._table)
        layout.addLayout(bottom)

        self._refresh()

    def _refresh(self) -> None:
        try:
            names = [b.name for b in self._queries.get_branches.execute() if b.is_remote]
        except Exception as e:
            QMessageBox.warning(self, "Load remote branches failed", str(e))
            names = []
        names = [n for n in names if not n.endswith("/HEAD")]
        try:
            self._defaults = set(self._queries.remote_default_branches.execute().values())
        except Exception:
            self._defaults = set()

        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for name in sorted(names):
            row = self._table.rowCount()
            self._table.insertRow(row)
            item = QTableWidgetItem(name)
            item.setData(Qt.UserRole, name)
            if name in self._defaults:
                item.setText(f"{name}  (default)")
                item.setFlags(Qt.ItemIsEnabled)
                item.setToolTip("Default branch — cannot be batch-deleted")
            else:
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
            self._table.setItem(row, 0, item)
        self._table.blockSignals(False)
        self._apply_filter(self._filter.text())
        self._update_delete_button()

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self._table.rowCount()):
            name = self._table.item(row, 0).data(Qt.UserRole)
            self._table.setRowHidden(row, needle not in name.lower())

    def _on_item_changed(self, _item) -> None:
        self._update_delete_button()

    def _checkable_items(self, *, visible_only: bool):
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if not (item.flags() & Qt.ItemIsUserCheckable):
                continue
            if visible_only and self._table.isRowHidden(row):
                continue
            yield item

    def _collect_selected(self) -> list[str]:
        return [
            item.data(Qt.UserRole)
            for item in self._checkable_items(visible_only=False)
            if item.checkState() == Qt.Checked
        ]

    def _select_all_visible(self) -> None:
        self._table.blockSignals(True)
        for item in self._checkable_items(visible_only=True):
            item.setCheckState(Qt.Checked)
        self._table.blockSignals(False)
        self._update_delete_button()

    def _clear_all(self) -> None:
        self._table.blockSignals(True)
        for item in self._checkable_items(visible_only=False):
            item.setCheckState(Qt.Unchecked)
        self._table.blockSignals(False)
        self._update_delete_button()

    def _update_delete_button(self) -> None:
        n = len(self._collect_selected())
        self._delete_btn.setText(f"Delete Selected ({n})")
        self._delete_btn.setEnabled(n > 0)

    @staticmethod
    def _grouped_by_remote(names: list[str]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for full in names:
            remote, branch = full.split("/", 1)
            grouped.setdefault(remote, []).append(branch)
        return grouped

    def _perform_deletions(self, grouped: dict[str, list[str]]) -> list[RemoteBranchDeleteResult]:
        results: list[RemoteBranchDeleteResult] = []
        for remote, branches in grouped.items():
            results.extend(self._commands.delete_remote_branches.execute(remote, branches))
        return results

    def _on_delete(self) -> None:
        selected = self._collect_selected()
        if not selected:
            return
        shown = "\n".join(selected[:_MAX_LISTED_IN_CONFIRM])
        if len(selected) > _MAX_LISTED_IN_CONFIRM:
            shown += f"\n… (+{len(selected) - _MAX_LISTED_IN_CONFIRM} more)"
        if (
            QMessageBox.question(
                self,
                "Delete remote branches",
                f"Delete {len(selected)} remote branch(es)? This cannot be undone.\n\n{shown}",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            != QMessageBox.Yes
        ):
            return

        grouped = self._grouped_by_remote(selected)
        self._set_busy(True)
        signals = _DeleteSignals(self)
        signals.finished.connect(self._on_delete_finished)
        signals.failed.connect(self._on_delete_failed)
        self._signals = signals  # prevent GC

        def _worker():
            try:
                results = self._perform_deletions(grouped)
                signals.finished.emit(results)
            except Exception as e:  # noqa: BLE001 - reported to the user
                signals.failed.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        for btn in (self._delete_btn, self._select_all_btn, self._clear_btn):
            btn.setEnabled(not busy)

    def _on_delete_finished(self, results: list) -> None:
        self._set_busy(False)
        ok = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]
        msg = f"{len(ok)} deleted"
        if failed:
            detail = "\n".join(f"  {r.branch} — {r.message}" for r in failed)
            msg += f", {len(failed)} failed:\n{detail}"
        QMessageBox.information(self, "Delete remote branches", msg)
        self._refresh()

    def _on_delete_failed(self, message: str) -> None:
        self._set_busy(False)
        QMessageBox.warning(self, "Delete remote branches failed", message)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/presentation/dialogs/test_remote_branches_dialog.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/dialogs/remote_branches_dialog.py tests/presentation/dialogs/test_remote_branches_dialog.py
git commit -m "feat(ui): RemoteBranchesDialog for batch remote-branch deletion"
```

---

### Task 7: Presentation — Git menu wiring

**Files:**
- Modify: `git_gui/presentation/menus/git_menu.py`
- Test: `tests/presentation/menus/test_git_menu_remote_branches.py` (create)

**Interfaces:**
- Consumes: `RemoteBranchesDialog` (Task 6).
- Produces: a `"Remote &Branches..."` `QAction` stored as `window._git_remote_branches_action`.

- [ ] **Step 1: Write the failing test**

Create `tests/presentation/menus/test_git_menu_remote_branches.py`:

```python
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.menus.git_menu import install_git_menu


def test_remote_branches_action_installed_and_opens(qtbot):
    win = QMainWindow()
    qtbot.addWidget(win)
    queries, commands = MagicMock(), MagicMock()

    install_git_menu(
        win,
        queries=queries,
        commands=commands,
        repo_workdir="/repo",
        on_open_submodule=lambda _p: None,
    )

    action = win._git_remote_branches_action
    assert action.text() == "Remote &Branches..."

    with patch(
        "git_gui.presentation.menus.git_menu.RemoteBranchesDialog"
    ) as DlgCls:
        action.trigger()
    DlgCls.assert_called_once_with(queries, commands, win)
    DlgCls.return_value.exec.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/presentation/menus/test_git_menu_remote_branches.py -v`
Expected: FAIL with `AttributeError: ... no attribute '_git_remote_branches_action'`.

- [ ] **Step 3: Implement the menu action**

In `git_gui/presentation/menus/git_menu.py`:

1. Add the import near the other dialog imports (line 10-12):

```python
from git_gui.presentation.dialogs.remote_branches_dialog import RemoteBranchesDialog
```

2. After the `branches_action` block (after line 59, `branches_action.triggered.connect(_open_branches)`), add:

```python
    remote_branches_action = QAction("Remote &Branches...", window)

    def _open_remote_branches() -> None:
        if queries is None or commands is None:
            return
        RemoteBranchesDialog(queries, commands, window).exec()

    remote_branches_action.triggered.connect(_open_remote_branches)
```

3. Add it to the menu after `git_menu.addAction(branches_action)` (line 73):

```python
    git_menu.addAction(remote_branches_action)
```

4. Store the reference next to the other `window._git_*_action` assignments (after line 88):

```python
    window._git_remote_branches_action = remote_branches_action  # type: ignore[attr-defined]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/presentation/menus/test_git_menu_remote_branches.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/menus/git_menu.py tests/presentation/menus/test_git_menu_remote_branches.py
git commit -m "feat(ui): add 'Remote Branches…' to the Git menu"
```

---

### Task 8: Full verification

- [ ] **Step 1: Run the whole suite + linters**

Run:
```bash
uv run pytest tests/ -q
uv run ruff check .
uv run ruff format --check .
```
Expected: all tests pass; ruff clean. If `ruff format --check` flags files, run `uv run ruff format <files>` and amend the relevant commit (or add a `style: apply ruff format` commit).

- [ ] **Step 2: Manual smoke (optional but recommended)**

Launch the app, open **Git ▸ Remote Branches…**, confirm: remote branches list (no `*/HEAD`), the default branch shows `(default)` and is un-checkable, filter works, Select All counts correctly, and deleting a throwaway remote branch reports success and removes it from the list. Use the `run` skill if helpful.

---

## Notes for the implementer

- The deletion runs on a background thread; the only synchronous seam tested is `_perform_deletions`. Don't "simplify" by calling the command on the UI thread — network pushes would freeze the dialog.
- `_parse_porcelain_delete` is intentionally lenient (skips non-ref lines like `To …`/`Done`/`error:`); keep it that way so future git output additions don't break it.
- Keep the dialog free of infrastructure imports (only domain `RemoteBranchDeleteResult` + Qt) to satisfy the architecture boundary.
