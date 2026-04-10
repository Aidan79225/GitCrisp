# Merge Options Dialog — Design

**Status:** Draft
**Date:** 2026-04-10
**Scope:** Spec B of three (A: graph entry point, B: merge options UI, C: conflict resolution flow)

## Background

Spec A added merge/rebase entry points to the commit graph context menu. Currently, all merge operations (sidebar and graph) execute immediately with hard-coded behavior: fast-forward when possible, otherwise normal merge with an auto-generated commit message (`Merge branch '<name>'`). Users have no control over merge strategy and cannot edit the commit message.

This spec adds a merge dialog that appears before every merge operation (from both graph and sidebar), allowing the user to choose a strategy and edit the commit message.

Out of scope:
- Squash merge — not planned
- Rebase dialog / options — separate spec
- Conflict resolution UI — Spec C

## Goals

- Let users choose merge strategy: no-ff (default), ff-only, or allow-ff.
- Let users edit the merge commit message before committing.
- Unify all merge entry points (sidebar + graph) through the same dialog.
- Show merge analysis results (can fast-forward? up to date?) so the user can make an informed decision.

## MergeDialog UI

A modal `QDialog` opened by `main_window` before executing any merge.

### Layout

**Title bar:** `Merge <source> into <target>`

**Analysis label** (top of dialog, read-only):
- `"This merge can be fast-forwarded"` — when ff is possible
- `"This merge requires a merge commit"` — when only normal merge is possible
- `"Already up to date"` — defensive case; graph disable rules should prevent this, but handle gracefully

**Strategy radio buttons** (3 options):
- `No fast-forward (--no-ff)` — **selected by default**. Always creates a merge commit even when ff is possible.
- `Fast-forward only (--ff-only)` — only available when ff is possible. When ff is not possible, this radio is disabled with tooltip `"Cannot fast-forward this merge"`.
- `Allow fast-forward` — fast-forwards when possible, otherwise creates a merge commit.

**Commit message editor** (`QPlainTextEdit`):
- Pre-filled with `Merge branch '<source>'` (for branch targets) or `Merge commit <short_oid>` (for commit targets).
- Enable/disable rules:
  - no-ff selected → always enabled (merge commit will be created)
  - ff-only selected and ff possible → disabled (no merge commit)
  - allow-ff selected and ff possible → disabled (will fast-forward)
  - allow-ff selected and ff not possible → enabled (merge commit needed)

**Buttons:** `Merge` (primary, accepts dialog) + `Cancel` (rejects dialog).
- `Merge` button disabled when: ff-only is selected but ff is not possible (radio is disabled, but as a safety net).

### Return value

Dialog returns a dataclass `MergeRequest(strategy: MergeStrategy, message: str | None)`:
- `message` is `None` when the merge will fast-forward (no commit message needed).
- `message` is the user-edited string when a merge commit will be created.

## Architecture

### Domain (`domain/entities.py`)

New types:

```
MergeStrategy(str, Enum): NO_FF, FF_ONLY, ALLOW_FF

MergeAnalysisResult(frozen dataclass):
    can_ff: bool
    is_up_to_date: bool
```

### Domain (`domain/ports.py`)

`IRepositoryReader` gains:
- `merge_analysis(oid: str) -> MergeAnalysisResult`

`IRepositoryWriter` signature changes:
- `merge(branch: str, strategy: MergeStrategy, message: str | None) -> None`
- `merge_commit(oid: str, strategy: MergeStrategy, message: str | None) -> None`

### Infrastructure (`infrastructure/pygit2_repo.py`)

- `merge_analysis(oid: str)` — wraps `self._repo.merge_analysis(Oid(hex=oid))`, maps flags to `MergeAnalysisResult`.
- `merge()` / `merge_commit()` — pass strategy + message to `_merge_oid()`.
- `_merge_oid(target_oid, label, strategy, message)` — three code paths:
  - `NO_FF`: always `self._repo.merge(target_oid)` + create commit with user message. Even when ff is possible, force a merge commit.
  - `FF_ONLY`: if ff possible, fast-forward; otherwise raise `RuntimeError("Cannot fast-forward")`.
  - `ALLOW_FF`: current behavior — ff when possible, otherwise normal merge + user message.

### Application

- `application/queries.py`: new `GetMergeAnalysis` query. Takes source oid (resolved by caller), returns `MergeAnalysisResult`.
- `application/commands.py`: `Merge.execute()` and `MergeCommit.execute()` gain `strategy: MergeStrategy` and `message: str | None` parameters, passed through to the writer.

### Presentation

- `presentation/bus.py`: wire `GetMergeAnalysis` into `QueryBus`.
- `presentation/dialogs/merge_dialog.py` (new file): `MergeDialog(QDialog)` as described in the UI section.
- `presentation/main_window.py`:
  - `_on_merge(branch)`: resolve branch to oid → call `GetMergeAnalysis` → open `MergeDialog` → if accepted, call `Merge.execute(branch, strategy, message)`.
  - `_on_merge_commit(oid)`: call `GetMergeAnalysis(oid)` → open `MergeDialog` → if accepted, call `MergeCommit.execute(oid, strategy, message)`.
  - Both sidebar and graph merge signals already route to `_on_merge` / `_on_merge_commit`, so sidebar gets the dialog for free.

### Resolving branch to oid for merge_analysis

`_on_merge(branch)` needs to resolve the branch name to an oid to call `GetMergeAnalysis`. Use existing `GetBranches` query to find the target oid, or add a thin `resolve_branch_oid(name) -> str` reader method. Prefer whichever is simpler in the existing codebase.

### Error handling

- If `merge_analysis` fails → log error, do not open dialog.
- If merge execution fails (e.g. conflicts in Spec C territory) → existing try/except + log_panel pattern.
- Dialog cancel → no action taken.

## Testing

### Unit

- `tests/infrastructure/test_reads.py`:
  - `test_merge_analysis_can_ff` — branch ahead, linear history → `can_ff=True, is_up_to_date=False`
  - `test_merge_analysis_normal` — diverged history → `can_ff=False, is_up_to_date=False`
  - `test_merge_analysis_up_to_date` — same commit → `can_ff=False, is_up_to_date=True`

- `tests/infrastructure/test_writes.py`:
  - `test_merge_no_ff_creates_merge_commit_even_when_ff_possible` — linear history + NO_FF → HEAD is a merge commit with 2 parents
  - `test_merge_ff_only_raises_when_not_possible` — diverged history + FF_ONLY → raises RuntimeError
  - `test_merge_allow_ff_fast_forwards_when_possible` — linear history + ALLOW_FF → HEAD moves (no merge commit)

- `tests/application/test_commands.py`:
  - `Merge` / `MergeCommit` with strategy + message: confirm args forwarded to mock writer

- `tests/application/test_queries.py`:
  - `GetMergeAnalysis` passthrough

### Dialog (pytest-qt)

`tests/presentation/dialogs/test_merge_dialog.py`:
- FF possible: all 3 radios enabled; select ff-only → message editor disabled; select no-ff → message editor enabled
- FF not possible: ff-only radio disabled with tooltip; no-ff selected → message editor enabled; allow-ff selected → message editor enabled
- Strategy switch toggles message editor enable/disable correctly
- Merge button disabled when ff-only selected but ff not possible (safety net — radio should already be disabled)
- Dialog accept returns correct MergeRequest with strategy + message
- Dialog reject returns None / rejected

### Manual acceptance

- Sidebar: right-click branch → Merge → dialog appears with correct analysis label and default no-ff
- Graph: right-click commit → Merge branch → same dialog
- Graph: right-click commit → Merge commit → dialog with commit-style default message
- Edit message, change strategy, click Merge → operation executes with chosen options
- Cancel dialog → no merge happens, repo unchanged

## File change list

New:
- `git_gui/presentation/dialogs/merge_dialog.py`
- `tests/presentation/dialogs/test_merge_dialog.py`

Modified:
- `git_gui/domain/entities.py`
- `git_gui/domain/ports.py`
- `git_gui/infrastructure/pygit2_repo.py`
- `git_gui/application/queries.py`
- `git_gui/application/commands.py`
- `git_gui/presentation/bus.py`
- `git_gui/presentation/main_window.py`

Test files modified:
- `tests/infrastructure/test_reads.py`
- `tests/infrastructure/test_writes.py`
- `tests/application/test_commands.py`
- `tests/application/test_queries.py`
