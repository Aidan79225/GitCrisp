# Merge Options Dialog — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a merge dialog that lets users choose merge strategy (no-ff / ff-only / allow-ff) and edit the commit message before every merge, replacing the current direct-execute behavior.

**Architecture:** Add `MergeStrategy` enum and `MergeAnalysisResult` to domain, extend the writer's merge methods with strategy + message params, add a `GetMergeAnalysis` query, create a `MergeDialog` (QDialog), and rewire main_window merge handlers to open the dialog first.

**Tech Stack:** Python, PySide6 (Qt), pygit2, pytest, pytest-qt, uv.

**Spec:** `docs/superpowers/specs/2026-04-10-merge-options-dialog-design.md`

---

## File Structure

**New:**
- `git_gui/presentation/dialogs/merge_dialog.py` — MergeDialog QDialog
- `tests/presentation/dialogs/test_merge_dialog.py` — pytest-qt dialog tests

**Modified:**
- `git_gui/domain/entities.py` — MergeStrategy enum, MergeAnalysisResult dataclass
- `git_gui/domain/ports.py` — IRepositoryReader.merge_analysis(), IRepositoryWriter.merge()/merge_commit() signatures
- `git_gui/infrastructure/pygit2_repo.py` — implement merge_analysis(), update _merge_oid()
- `git_gui/application/queries.py` — GetMergeAnalysis query
- `git_gui/application/commands.py` — Merge/MergeCommit accept strategy+message
- `git_gui/presentation/bus.py` — wire GetMergeAnalysis
- `git_gui/presentation/main_window.py` — _on_merge/_on_merge_commit open dialog

**Test files modified:**
- `tests/infrastructure/test_reads.py`
- `tests/infrastructure/test_writes.py`
- `tests/application/test_commands.py`
- `tests/application/test_queries.py`

---

## Task 1: Add MergeStrategy enum and MergeAnalysisResult dataclass

**Files:**
- Modify: `git_gui/domain/entities.py`

- [ ] **Step 1: Add types to entities.py**

Append at the bottom of `git_gui/domain/entities.py` (note: `Enum`, `dataclass` are already imported):

```python
class MergeStrategy(str, Enum):
    NO_FF = "NO_FF"
    FF_ONLY = "FF_ONLY"
    ALLOW_FF = "ALLOW_FF"


@dataclass(frozen=True)
class MergeAnalysisResult:
    can_ff: bool
    is_up_to_date: bool
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from git_gui.domain.entities import MergeStrategy, MergeAnalysisResult; print(MergeStrategy.NO_FF, MergeAnalysisResult(True, False))"`
Expected: `MergeStrategy.NO_FF MergeAnalysisResult(can_ff=True, is_up_to_date=False)`

- [ ] **Step 3: Commit**

```bash
git add git_gui/domain/entities.py
git commit -m "feat(domain): add MergeStrategy enum and MergeAnalysisResult dataclass"
```

---

## Task 2: Extend reader/writer protocols

**Files:**
- Modify: `git_gui/domain/ports.py`

- [ ] **Step 1: Add merge_analysis to reader**

In `git_gui/domain/ports.py`, update the import line to include the new types:

```python
from git_gui.domain.entities import Branch, Commit, CommitStat, FileStatus, Hunk, LocalBranchInfo, MergeAnalysisResult, MergeStrategy, Remote, RepoStateInfo, Stash, Submodule, Tag
```

Add at the bottom of `IRepositoryReader` protocol body:

```python
    def merge_analysis(self, oid: str) -> MergeAnalysisResult: ...
```

- [ ] **Step 2: Update writer signatures**

Replace the existing `merge` and `merge_commit` lines in `IRepositoryWriter`:

```python
    def merge(self, branch: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None: ...
    def merge_commit(self, oid: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None: ...
```

The default `ALLOW_FF` preserves backward compatibility with existing callers that don't pass strategy (e.g., tests from Spec A).

- [ ] **Step 3: Verify**

Run: `uv run python -c "from git_gui.domain.ports import IRepositoryReader, IRepositoryWriter; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add git_gui/domain/ports.py
git commit -m "feat(domain): add merge_analysis reader and strategy params to writer"
```

---

## Task 3: Implement merge_analysis on Pygit2Repository (TDD)

**Files:**
- Test: `tests/infrastructure/test_reads.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Write failing tests**

First read the top of `tests/infrastructure/test_reads.py` to find the existing fixture pattern (uses `repo_impl` and `repo_path` from `tests/conftest.py`). Add these tests at the bottom:

```python
def test_merge_analysis_can_ff(repo_impl, repo_path):
    """Linear history: feature is ahead of main → can fast-forward."""
    head_oid = repo_impl.get_head_oid()
    repo_impl.create_branch("feature", head_oid)
    repo_impl.checkout("feature")
    (repo_path / "ff.txt").write_text("ff")
    repo_impl.stage(["ff.txt"])
    new = repo_impl.commit("ahead")
    branches = repo_impl.get_branches()
    main_name = next(b.name for b in branches if not b.is_remote and b.name != "feature")
    repo_impl.checkout(main_name)

    result = repo_impl.merge_analysis(new.oid)
    assert result.can_ff is True
    assert result.is_up_to_date is False


def test_merge_analysis_normal(repo_impl, repo_path):
    """Diverged history → cannot fast-forward."""
    head_oid = repo_impl.get_head_oid()
    repo_impl.create_branch("diverge", head_oid)
    # Commit on main
    (repo_path / "main_side.txt").write_text("m")
    repo_impl.stage(["main_side.txt"])
    repo_impl.commit("main side")
    # Commit on diverge
    repo_impl.checkout("diverge")
    (repo_path / "diverge_side.txt").write_text("d")
    repo_impl.stage(["diverge_side.txt"])
    diverge_commit = repo_impl.commit("diverge side")
    branches = repo_impl.get_branches()
    main_name = next(b.name for b in branches if not b.is_remote and b.name not in ("diverge",))
    repo_impl.checkout(main_name)

    result = repo_impl.merge_analysis(diverge_commit.oid)
    assert result.can_ff is False
    assert result.is_up_to_date is False


def test_merge_analysis_up_to_date(repo_impl, repo_path):
    """Same commit → already up to date."""
    head_oid = repo_impl.get_head_oid()
    result = repo_impl.merge_analysis(head_oid)
    assert result.is_up_to_date is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_reads.py -v -k merge_analysis`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement**

In `git_gui/infrastructure/pygit2_repo.py`, add `MergeAnalysisResult` to the entities import line. Then add this method to `Pygit2Repository` (near the merge methods):

```python
def merge_analysis(self, oid: str) -> MergeAnalysisResult:
    target = pygit2.Oid(hex=oid)
    result, _ = self._repo.merge_analysis(target)
    can_ff = bool(result & pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD)
    is_up_to_date = bool(result & pygit2.GIT_MERGE_ANALYSIS_UP_TO_DATE)
    return MergeAnalysisResult(can_ff=can_ff, is_up_to_date=is_up_to_date)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/infrastructure/test_reads.py -v -k merge_analysis`
Expected: All 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_reads.py
git commit -m "feat(infra): implement merge_analysis()"
```

---

## Task 4: Update _merge_oid to accept strategy and message (TDD)

**Files:**
- Test: `tests/infrastructure/test_writes.py`
- Modify: `git_gui/infrastructure/pygit2_repo.py`

- [ ] **Step 1: Write failing tests**

Read the top of `tests/infrastructure/test_writes.py` for the fixture pattern (`writable_repo` fixture or `repo_impl`/`repo_path`). Append these tests:

```python
from git_gui.domain.entities import MergeStrategy


def test_merge_no_ff_creates_merge_commit_when_ff_possible(repo_impl, repo_path):
    """NO_FF forces a merge commit even on linear history."""
    head_oid = repo_impl.get_head_oid()
    repo_impl.create_branch("feature", head_oid)
    repo_impl.checkout("feature")
    (repo_path / "noff.txt").write_text("noff")
    repo_impl.stage(["noff.txt"])
    feat_commit = repo_impl.commit("feature work")
    branches = repo_impl.get_branches()
    main_name = next(b.name for b in branches if not b.is_remote and b.name != "feature")
    repo_impl.checkout(main_name)

    repo_impl.merge("feature", strategy=MergeStrategy.NO_FF, message="Custom merge msg")

    new_head = repo_impl.get_commit(repo_impl.get_head_oid())
    assert len(new_head.parents) == 2  # merge commit
    assert "Custom merge msg" in new_head.message


def test_merge_ff_only_raises_when_not_possible(repo_impl, repo_path):
    """FF_ONLY on diverged history → raises."""
    head_oid = repo_impl.get_head_oid()
    repo_impl.create_branch("diverge", head_oid)
    (repo_path / "m.txt").write_text("m")
    repo_impl.stage(["m.txt"])
    repo_impl.commit("main side")
    repo_impl.checkout("diverge")
    (repo_path / "d.txt").write_text("d")
    repo_impl.stage(["d.txt"])
    repo_impl.commit("diverge side")
    branches = repo_impl.get_branches()
    main_name = next(b.name for b in branches if not b.is_remote and b.name != "diverge")
    repo_impl.checkout(main_name)

    import pytest
    with pytest.raises(RuntimeError, match="[Cc]annot fast-forward"):
        repo_impl.merge("diverge", strategy=MergeStrategy.FF_ONLY)


def test_merge_allow_ff_fast_forwards_when_possible(repo_impl, repo_path):
    """ALLOW_FF on linear history → fast-forward (no merge commit)."""
    head_oid = repo_impl.get_head_oid()
    repo_impl.create_branch("feature", head_oid)
    repo_impl.checkout("feature")
    (repo_path / "af.txt").write_text("af")
    repo_impl.stage(["af.txt"])
    feat_commit = repo_impl.commit("feature work")
    branches = repo_impl.get_branches()
    main_name = next(b.name for b in branches if not b.is_remote and b.name != "feature")
    repo_impl.checkout(main_name)

    repo_impl.merge("feature", strategy=MergeStrategy.ALLOW_FF)

    assert repo_impl.get_head_oid() == feat_commit.oid
    new_head = repo_impl.get_commit(repo_impl.get_head_oid())
    assert len(new_head.parents) == 1  # fast-forwarded, not a merge commit
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_writes.py -v -k "merge_no_ff or merge_ff_only_raises or merge_allow_ff"`
Expected: FAIL — `merge()` doesn't accept `strategy` yet.

- [ ] **Step 3: Update merge/merge_commit/_merge_oid**

In `git_gui/infrastructure/pygit2_repo.py`, add `MergeStrategy` to the entities import. Then replace the three methods:

```python
def merge(self, branch: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None:
    if branch in self._repo.branches.local:
        ref = self._repo.branches.local[branch]
    else:
        ref = self._repo.branches.remote[branch]
    default_label = f"branch '{branch}'"
    self._merge_oid(ref.target, label=default_label, strategy=strategy, message=message)

def merge_commit(self, oid: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None:
    target = pygit2.Oid(hex=oid)
    default_label = f"commit {oid[:7]}"
    self._merge_oid(target, label=default_label, strategy=strategy, message=message)

def _merge_oid(self, target_oid, label: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None:
    merge_result, _ = self._repo.merge_analysis(target_oid)
    can_ff = bool(merge_result & pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD)

    commit_message = message if message else f"Merge {label}"

    if strategy == MergeStrategy.FF_ONLY:
        if can_ff:
            self._repo.checkout_tree(self._repo.get(target_oid))
            self._repo.head.set_target(target_oid)
        else:
            raise RuntimeError("Cannot fast-forward this merge")
    elif strategy == MergeStrategy.NO_FF:
        # Force merge commit even when ff is possible
        self._repo.merge(target_oid)
        if not self._repo.index.conflicts:
            self._repo.index.write()
            tree = self._repo.index.write_tree()
            sig = self._get_signature()
            self._repo.create_commit(
                "HEAD", sig, sig,
                commit_message,
                tree,
                [self._repo.head.target, target_oid],
            )
            self._repo.state_cleanup()
    else:  # ALLOW_FF
        if can_ff:
            self._repo.checkout_tree(self._repo.get(target_oid))
            self._repo.head.set_target(target_oid)
        elif merge_result & pygit2.GIT_MERGE_ANALYSIS_NORMAL:
            self._repo.merge(target_oid)
            if not self._repo.index.conflicts:
                self._repo.index.write()
                tree = self._repo.index.write_tree()
                sig = self._get_signature()
                self._repo.create_commit(
                    "HEAD", sig, sig,
                    commit_message,
                    tree,
                    [self._repo.head.target, target_oid],
                )
                self._repo.state_cleanup()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/infrastructure/test_writes.py -v -k "merge_no_ff or merge_ff_only_raises or merge_allow_ff"`
Expected: All 3 PASS.

- [ ] **Step 5: Run full suite for regressions**

Run: `uv run pytest tests/ -x -q`
Expected: All pass (existing callers use default `ALLOW_FF` which matches old behavior).

- [ ] **Step 6: Commit**

```bash
git add git_gui/infrastructure/pygit2_repo.py tests/infrastructure/test_writes.py
git commit -m "feat(infra): update _merge_oid with strategy and message support"
```

---

## Task 5: Add GetMergeAnalysis query (TDD)

**Files:**
- Test: `tests/application/test_queries.py`
- Modify: `git_gui/application/queries.py`

- [ ] **Step 1: Write failing test**

Append to `tests/application/test_queries.py`:

```python
from git_gui.application.queries import GetMergeAnalysis
from git_gui.domain.entities import MergeAnalysisResult


class _FakeMergeAnalysisReader:
    def merge_analysis(self, oid):
        return MergeAnalysisResult(can_ff=True, is_up_to_date=False)


def test_get_merge_analysis_passthrough():
    q = GetMergeAnalysis(_FakeMergeAnalysisReader())
    result = q.execute("abc123")
    assert result.can_ff is True
    assert result.is_up_to_date is False
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/application/test_queries.py::test_get_merge_analysis_passthrough -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

Add `MergeAnalysisResult` to the entities import at the top of `git_gui/application/queries.py`. Append:

```python
class GetMergeAnalysis:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, oid: str) -> MergeAnalysisResult:
        return self._reader.merge_analysis(oid)
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/application/test_queries.py::test_get_merge_analysis_passthrough -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add git_gui/application/queries.py tests/application/test_queries.py
git commit -m "feat(application): add GetMergeAnalysis query"
```

---

## Task 6: Update Merge/MergeCommit commands (TDD)

**Files:**
- Test: `tests/application/test_commands.py`
- Modify: `git_gui/application/commands.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/application/test_commands.py`:

```python
from git_gui.domain.entities import MergeStrategy


class _FakeStrategyWriter:
    def __init__(self):
        self.merge_args = None
        self.merge_commit_args = None
    def merge(self, branch, strategy=None, message=None):
        self.merge_args = (branch, strategy, message)
    def merge_commit(self, oid, strategy=None, message=None):
        self.merge_commit_args = (oid, strategy, message)


def test_merge_passes_strategy_and_message():
    w = _FakeStrategyWriter()
    Merge(w).execute("feature", strategy=MergeStrategy.NO_FF, message="custom")
    assert w.merge_args == ("feature", MergeStrategy.NO_FF, "custom")


def test_merge_commit_passes_strategy_and_message():
    w = _FakeStrategyWriter()
    MergeCommit(w).execute("abc123", strategy=MergeStrategy.FF_ONLY, message=None)
    assert w.merge_commit_args == ("abc123", MergeStrategy.FF_ONLY, None)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/application/test_commands.py -v -k "merge_passes_strategy or merge_commit_passes_strategy"`
Expected: FAIL — `execute()` doesn't accept strategy.

- [ ] **Step 3: Update commands**

In `git_gui/application/commands.py`, add `MergeStrategy` to imports:

```python
from git_gui.domain.entities import Branch, Commit, MergeStrategy
```

Replace the `Merge` class:

```python
class Merge:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, branch: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None:
        self._writer.merge(branch, strategy=strategy, message=message)
```

Replace the `MergeCommit` class:

```python
class MergeCommit:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, oid: str, strategy: MergeStrategy = MergeStrategy.ALLOW_FF, message: str | None = None) -> None:
        self._writer.merge_commit(oid, strategy=strategy, message=message)
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/application/test_commands.py -v -k "merge_passes_strategy or merge_commit_passes_strategy"`
Expected: PASS.

- [ ] **Step 5: Full suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add git_gui/application/commands.py tests/application/test_commands.py
git commit -m "feat(application): add strategy and message params to Merge/MergeCommit"
```

---

## Task 7: Wire GetMergeAnalysis into bus

**Files:**
- Modify: `git_gui/presentation/bus.py`

- [ ] **Step 1: Update imports and dataclass**

In `git_gui/presentation/bus.py`, add `GetMergeAnalysis` to the queries import line:

```python
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes, GetTags, GetRemoteTags, GetCommitStats,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
    GetCommitDetail, IsDirty, GetHeadOid,
    ListRemotes, ListSubmodules, ListLocalBranchesWithUpstream,
    GetRepoState, IsAncestor, GetMergeAnalysis,
)
```

Add `get_merge_analysis: GetMergeAnalysis` to the `QueryBus` dataclass fields. Add `get_merge_analysis=GetMergeAnalysis(reader),` to the `from_reader` classmethod.

- [ ] **Step 2: Verify**

Run: `uv run python -c "from git_gui.presentation.bus import QueryBus; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Full suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add git_gui/presentation/bus.py
git commit -m "feat(bus): wire GetMergeAnalysis query"
```

---

## Task 8: Create MergeDialog

**Files:**
- Create: `git_gui/presentation/dialogs/merge_dialog.py`

- [ ] **Step 1: Create the dialog**

Create `git_gui/presentation/dialogs/merge_dialog.py` with this content:

```python
from __future__ import annotations
from dataclasses import dataclass
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPlainTextEdit,
    QRadioButton, QVBoxLayout,
)
from git_gui.domain.entities import MergeStrategy


@dataclass
class MergeRequest:
    strategy: MergeStrategy
    message: str | None


class MergeDialog(QDialog):
    """Dialog for choosing merge strategy and editing commit message."""

    def __init__(
        self,
        source_label: str,
        target_label: str,
        can_ff: bool,
        default_message: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Merge {source_label} into {target_label}")
        self.setMinimumWidth(480)
        self._can_ff = can_ff

        layout = QVBoxLayout(self)

        # Analysis label
        if can_ff:
            hint = "This merge can be fast-forwarded"
        else:
            hint = "This merge requires a merge commit"
        self._analysis_label = QLabel(hint)
        self._analysis_label.setStyleSheet("font-style: italic; padding: 4px;")
        layout.addWidget(self._analysis_label)

        # Strategy radios
        self._radio_no_ff = QRadioButton("No fast-forward (--no-ff)")
        self._radio_ff_only = QRadioButton("Fast-forward only (--ff-only)")
        self._radio_allow_ff = QRadioButton("Allow fast-forward")

        self._radio_no_ff.setChecked(True)

        if not can_ff:
            self._radio_ff_only.setEnabled(False)
            self._radio_ff_only.setToolTip("Cannot fast-forward this merge")

        self._radio_no_ff.toggled.connect(self._on_strategy_changed)
        self._radio_ff_only.toggled.connect(self._on_strategy_changed)
        self._radio_allow_ff.toggled.connect(self._on_strategy_changed)

        layout.addWidget(self._radio_no_ff)
        layout.addWidget(self._radio_ff_only)
        layout.addWidget(self._radio_allow_ff)

        # Commit message editor
        self._message_label = QLabel("Commit message:")
        layout.addWidget(self._message_label)

        self._message_edit = QPlainTextEdit()
        self._message_edit.setPlainText(default_message)
        self._message_edit.setMinimumHeight(80)
        layout.addWidget(self._message_edit)

        # Buttons
        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Merge")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        # Apply initial state
        self._on_strategy_changed()

    def _will_create_merge_commit(self) -> bool:
        if self._radio_no_ff.isChecked():
            return True
        if self._radio_ff_only.isChecked():
            return False  # ff only → no merge commit
        # allow-ff
        return not self._can_ff

    def _on_strategy_changed(self) -> None:
        will_commit = self._will_create_merge_commit()
        self._message_edit.setEnabled(will_commit)
        self._message_label.setEnabled(will_commit)

        # Safety net: disable Merge button if ff-only but can't ff
        merge_btn = self._buttons.button(QDialogButtonBox.Ok)
        if self._radio_ff_only.isChecked() and not self._can_ff:
            merge_btn.setEnabled(False)
        else:
            merge_btn.setEnabled(True)

    def result_value(self) -> MergeRequest:
        if self._radio_no_ff.isChecked():
            strategy = MergeStrategy.NO_FF
        elif self._radio_ff_only.isChecked():
            strategy = MergeStrategy.FF_ONLY
        else:
            strategy = MergeStrategy.ALLOW_FF

        if self._will_create_merge_commit():
            message = self._message_edit.toPlainText()
        else:
            message = None

        return MergeRequest(strategy=strategy, message=message)
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from git_gui.presentation.dialogs.merge_dialog import MergeDialog, MergeRequest; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/dialogs/merge_dialog.py
git commit -m "feat(dialogs): create MergeDialog with strategy and message editing"
```

---

## Task 9: MergeDialog tests (pytest-qt)

**Files:**
- Create: `tests/presentation/dialogs/test_merge_dialog.py`

- [ ] **Step 1: Write the tests**

Create `tests/presentation/dialogs/test_merge_dialog.py` (if `tests/presentation/dialogs/__init__.py` doesn't exist, create it as empty first):

```python
from __future__ import annotations
import pytest
from PySide6.QtWidgets import QDialogButtonBox
from git_gui.domain.entities import MergeStrategy
from git_gui.presentation.dialogs.merge_dialog import MergeDialog, MergeRequest


def test_default_strategy_is_no_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="Merge branch 'feature'")
    qtbot.addWidget(dlg)
    assert dlg._radio_no_ff.isChecked()


def test_ff_possible_all_radios_enabled(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    assert dlg._radio_no_ff.isEnabled()
    assert dlg._radio_ff_only.isEnabled()
    assert dlg._radio_allow_ff.isEnabled()


def test_ff_not_possible_ff_only_disabled(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=False, default_message="msg")
    qtbot.addWidget(dlg)
    assert dlg._radio_ff_only.isEnabled() is False
    assert "Cannot fast-forward" in dlg._radio_ff_only.toolTip()


def test_no_ff_message_editor_enabled(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_no_ff.setChecked(True)
    assert dlg._message_edit.isEnabled() is True


def test_ff_only_message_editor_disabled(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_ff_only.setChecked(True)
    assert dlg._message_edit.isEnabled() is False


def test_allow_ff_can_ff_message_editor_disabled(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_allow_ff.setChecked(True)
    assert dlg._message_edit.isEnabled() is False


def test_allow_ff_cannot_ff_message_editor_enabled(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=False, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_allow_ff.setChecked(True)
    assert dlg._message_edit.isEnabled() is True


def test_analysis_label_can_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    assert "fast-forwarded" in dlg._analysis_label.text()


def test_analysis_label_cannot_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=False, default_message="msg")
    qtbot.addWidget(dlg)
    assert "requires a merge commit" in dlg._analysis_label.text()


def test_result_value_no_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="Merge branch 'feature'")
    qtbot.addWidget(dlg)
    dlg._radio_no_ff.setChecked(True)
    dlg._message_edit.setPlainText("Custom message")
    result = dlg.result_value()
    assert result.strategy == MergeStrategy.NO_FF
    assert result.message == "Custom message"


def test_result_value_ff_only(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_ff_only.setChecked(True)
    result = dlg.result_value()
    assert result.strategy == MergeStrategy.FF_ONLY
    assert result.message is None


def test_result_value_allow_ff_can_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_allow_ff.setChecked(True)
    result = dlg.result_value()
    assert result.strategy == MergeStrategy.ALLOW_FF
    assert result.message is None


def test_result_value_allow_ff_cannot_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=False, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_allow_ff.setChecked(True)
    dlg._message_edit.setPlainText("Merge msg")
    result = dlg.result_value()
    assert result.strategy == MergeStrategy.ALLOW_FF
    assert result.message == "Merge msg"


def test_merge_button_disabled_when_ff_only_and_cannot_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=False, default_message="msg")
    qtbot.addWidget(dlg)
    # ff-only radio is disabled, but force it for safety-net test
    dlg._radio_ff_only.setEnabled(True)
    dlg._radio_ff_only.setChecked(True)
    merge_btn = dlg._buttons.button(QDialogButtonBox.Ok)
    assert merge_btn.isEnabled() is False
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/presentation/dialogs/test_merge_dialog.py -v`
Expected: All 14 tests PASS.

- [ ] **Step 3: Full suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tests/presentation/dialogs/test_merge_dialog.py tests/presentation/dialogs/__init__.py
git commit -m "test(dialogs): add MergeDialog pytest-qt tests"
```

---

## Task 10: Wire main_window handlers to use dialog

**Files:**
- Modify: `git_gui/presentation/main_window.py`

- [ ] **Step 1: Add import**

At the top of `git_gui/presentation/main_window.py`, add:

```python
from git_gui.presentation.dialogs.merge_dialog import MergeDialog
```

- [ ] **Step 2: Replace _on_merge handler**

Replace the existing `_on_merge` method (around line 208-215) with:

```python
def _on_merge(self, branch: str) -> None:
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
        analysis = self._queries.get_merge_analysis.execute(target.target_oid)
        head_branch = self._queries.get_repo_state.execute().head_branch or "HEAD"
        default_msg = f"Merge branch '{branch}'"

        if analysis.is_up_to_date:
            self._log_panel.log(f"Merge {branch}: already up to date")
            return

        dlg = MergeDialog(branch, head_branch, analysis.can_ff, default_msg, parent=self)
        if dlg.exec() != MergeDialog.Accepted:
            return
        req = dlg.result_value()
        self._commands.merge.execute(branch, strategy=req.strategy, message=req.message)
        self._log_panel.log(f"Merge: {branch} into {head_branch}")
    except Exception as e:
        self._log_panel.expand()
        self._log_panel.log_error(f"Merge {branch} — ERROR: {e}")
    self._reload()
```

- [ ] **Step 3: Replace _on_merge_commit handler**

Replace the existing `_on_merge_commit` method (around line 226-233) with:

```python
def _on_merge_commit(self, oid: str) -> None:
    try:
        analysis = self._queries.get_merge_analysis.execute(oid)
        head_branch = self._queries.get_repo_state.execute().head_branch or "HEAD"
        short_oid = oid[:7]
        default_msg = f"Merge commit {short_oid}"

        if analysis.is_up_to_date:
            self._log_panel.log(f"Merge commit {short_oid}: already up to date")
            return

        dlg = MergeDialog(f"commit {short_oid}", head_branch, analysis.can_ff, default_msg, parent=self)
        if dlg.exec() != MergeDialog.Accepted:
            return
        req = dlg.result_value()
        self._commands.merge_commit.execute(oid, strategy=req.strategy, message=req.message)
        self._log_panel.log(f"Merge: commit {short_oid} into {head_branch}")
    except Exception as e:
        self._log_panel.expand()
        self._log_panel.log_error(f"Merge commit {short_oid} — ERROR: {e}")
    self._reload()
```

- [ ] **Step 4: Verify import**

Run: `uv run python -c "from git_gui.presentation.main_window import MainWindow; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Full suite**

Run: `uv run pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/main_window.py
git commit -m "feat(main_window): wire merge dialog for all merge entry points"
```

---

## Task 11: Manual acceptance pass

- [ ] **Step 1: Launch the app**

Run: `uv run python main.py` (or whatever the project's entry point is).

- [ ] **Step 2: Verify each scenario**

1. **Sidebar merge:** Right-click a branch in the sidebar → Merge → dialog appears with correct title, analysis label, and default no-ff selected.
2. **Graph branch merge:** Right-click a commit with branches → Merge branch → dialog appears.
3. **Graph commit merge:** Right-click a commit → Merge commit → dialog with "Merge commit abc1234" default message.
4. **Strategy switching:** Select each radio — message editor enables/disables correctly.
5. **FF analysis:** On a linear branch (can ff): all 3 radios enabled, "can be fast-forwarded" label. On a diverged branch: ff-only radio disabled.
6. **Custom message:** Edit message, select no-ff, click Merge → check `git log` shows custom message.
7. **Cancel:** Open dialog, click Cancel → no merge happens.
8. **Up-to-date:** Try to merge HEAD into itself → "already up to date" logged, no dialog.

- [ ] **Step 3: Commit any fixes**

If manual testing reveals issues, fix and commit with descriptive messages.

---

## Out of Scope

- Squash merge — not planned
- Rebase dialog / options — separate spec
- Conflict resolution UI — Spec C
