# Conflict Resolution Flow — Design

**Status:** Draft
**Date:** 2026-04-10
**Scope:** Spec C of three (A: graph entry point, B: merge options UI, C: conflict resolution flow)

## Background

When a merge or rebase produces conflicts, GitStack currently handles it poorly: `_merge_oid` silently exits when `index.conflicts` is truthy, leaving the repo in MERGING state with no user-facing indication. The graph shows a generic "Uncommitted Changes" row, the working tree has no conflict markers, and there are no abort/continue controls. Users have no way to resolve conflicts or escape the merge state without using the command line.

This spec adds conflict state awareness throughout the UI: graph visualization with merge parents, a conflict banner with abort/continue, and conflict file indicators.

Out of scope:
- Built-in conflict diff resolution (choose ours/theirs) — separate spec
- External merge tool integration — separate spec
- Rebase skip — separate spec
- File watcher for auto-reload — separate spec

## Goals

- Make merge/rebase conflict states clearly visible in the graph and working tree.
- Let users abort or continue merge/rebase operations without leaving GitStack.
- Show conflict files prominently so users know what to fix.
- Handle both MERGING and REBASING states with appropriate behavior differences.

## Graph Visualization

### Synthetic row during MERGING

When repo state is MERGING and the working tree is dirty:
- Message: `"Merge in progress (conflicts)"` (replaces "Uncommitted Changes")
- Parents: `[HEAD_oid, merge_head_oid]` — the graph draws two lines converging into the synthetic row, showing the merge visually.
- `merge_head_oid` is read from `.git/MERGE_HEAD` via a new `get_merge_head()` reader method.

### Synthetic row during REBASING

When repo state is REBASING and the working tree is dirty:
- Message: `"Rebase in progress"`
- Parents: `[HEAD_oid]` — single parent (rebase is linear). No special graph shape.

### Normal dirty state (CLEAN)

No change — "Uncommitted Changes" with `[HEAD_oid]` parent as today.

### New query needed

`GetMergeHead` — returns the oid from `.git/MERGE_HEAD` or None. Used by graph reload logic to construct the synthetic row's parents.

## Working Tree Banner

A conditional banner bar at the top of the working tree widget.

### Visibility

- MERGING state → visible, text: `"Merge in progress"`
- REBASING state → visible, text: `"Rebase in progress"`
- CLEAN / other states → hidden

### Controls

Two buttons on the banner:

**Abort:**
- MERGING → calls `git merge --abort` (new writer method `merge_abort()`)
- REBASING → calls `git rebase --abort` (new writer method `rebase_abort()`)
- After execution: reload. Repo returns to CLEAN state, banner disappears.

**Continue:**
- First checks `has_unresolved_conflicts()`. If true → show error message in log panel: "Resolve all conflicts and stage files first"
- If no unresolved conflicts:
  - MERGING → read `.git/MERGE_MSG` for the pre-filled commit message, call `commit()` to finalize the merge (equivalent to `git merge --continue`)
  - REBASING → call `rebase_continue()` (new writer method, wraps `git rebase --continue`)
- After execution: reload.

### Merge commit message

The commit message for merge continue comes from `.git/MERGE_MSG`, which git populates when the merge starts. If the user edited the message in the Spec B MergeDialog before the merge began, that message is already stored in `.git/MERGE_MSG`. No additional dialog is needed.

## Conflict File Indicators

### Working tree display

- The existing `get_working_tree()` already returns `FileStatus` with `status="conflicted"` from pygit2.
- Change the delta label mapping: `"conflicted"` currently shows as `"?"` — change to `"C"` with a distinct color (red or orange) so conflict files stand out.
- Sort conflict files to the top of the working tree list.

## Architecture

### Domain (`domain/entities.py`)

No new types. `RepoState` enum already has MERGING and REBASING.

### Ports (`domain/ports.py`)

`IRepositoryReader` gains:
- `get_merge_head() -> str | None` — read `.git/MERGE_HEAD`
- `get_merge_msg() -> str | None` — read `.git/MERGE_MSG`
- `has_unresolved_conflicts() -> bool` — check if index has conflict entries

`IRepositoryWriter` gains:
- `merge_abort() -> None`
- `rebase_abort() -> None`
- `rebase_continue() -> None`

### Infrastructure (`infrastructure/pygit2_repo.py`)

Implement the 6 new methods:
- `get_merge_head()`: read `{repo.path}/MERGE_HEAD`, parse first line as oid hex string, return None if file doesn't exist.
- `get_merge_msg()`: read `{repo.path}/MERGE_MSG`, return full content as string, return None if file doesn't exist.
- `has_unresolved_conflicts()`: check `self._repo.index.conflicts` is truthy (non-None and non-empty).
- `merge_abort()`: run `git merge --abort` via subprocess.
- `rebase_abort()`: run `git rebase --abort` via subprocess.
- `rebase_continue()`: run `git rebase --continue` via subprocess.

Note: merge continue does not need a dedicated writer method — it is a normal `commit()` call using the message from `get_merge_msg()`.

### Application

Queries (`queries.py`):
- `GetMergeHead` — wraps `reader.get_merge_head()`
- `GetMergeMsg` — wraps `reader.get_merge_msg()`
- `HasUnresolvedConflicts` — wraps `reader.has_unresolved_conflicts()`

Commands (`commands.py`):
- `MergeAbort` — wraps `writer.merge_abort()`
- `RebaseAbort` — wraps `writer.rebase_abort()`
- `RebaseContinue` — wraps `writer.rebase_continue()`

### Presentation

`bus.py`: wire all new queries and commands.

`graph.py`: in the reload callback, after checking `is_dirty`, also check `repo_state` and `get_merge_head`. Adjust synthetic commit's message and parents based on state:
- MERGING + merge_head exists → message `"Merge in progress (conflicts)"`, parents `[head_oid, merge_head_oid]`
- REBASING → message `"Rebase in progress"`, parents `[head_oid]`
- Otherwise → existing behavior

`working_tree.py`:
- Add a banner widget (QWidget with QHBoxLayout: QLabel + Abort QPushButton + Continue QPushButton) at the top of the layout.
- On reload, query `repo_state` and show/hide the banner. Update label text based on state.
- Emit signals for abort/continue button clicks.
- Sort conflict files to top of the file list.
- Change conflicted delta label from `"?"` to `"C"` with red/orange color.

`main_window.py`:
- Wire banner abort/continue signals to new handlers.
- Abort handler: call MergeAbort or RebaseAbort based on current state, log result, reload.
- Continue handler: check HasUnresolvedConflicts → if true, log error. If false, for MERGING: read GetMergeMsg + call commit. For REBASING: call RebaseContinue. Log result, reload.

## Testing

### Infrastructure integration tests

`tests/infrastructure/test_reads.py`:
- `test_get_merge_head_returns_oid_during_merge` — create conflict via divergent branches, trigger merge, confirm merge_head matches target branch tip
- `test_get_merge_head_returns_none_when_clean`
- `test_get_merge_msg_returns_content_during_merge`
- `test_has_unresolved_conflicts_true_during_merge`
- `test_has_unresolved_conflicts_false_when_clean`

`tests/infrastructure/test_writes.py`:
- `test_merge_abort_restores_clean_state` — merge conflict → abort → repo_state is CLEAN, MERGE_HEAD gone
- `test_rebase_abort_restores_clean_state`
- `test_rebase_continue_after_resolving` — rebase conflict → resolve + stage → continue → state CLEAN, commit applied

### Application unit tests

`tests/application/test_queries.py`: mock passthrough tests for GetMergeHead, GetMergeMsg, HasUnresolvedConflicts
`tests/application/test_commands.py`: mock passthrough tests for MergeAbort, RebaseAbort, RebaseContinue

### Widget tests (pytest-qt)

`tests/presentation/widgets/test_working_tree_banner.py` (new):
- MERGING state → banner visible, label says "Merge in progress", both buttons present
- REBASING state → banner visible, label says "Rebase in progress"
- CLEAN state → banner hidden
- Abort button click → correct signal emitted
- Continue button click → correct signal emitted

`tests/presentation/test_graph_model.py` (extend):
- MERGING + dirty → synthetic row message is "Merge in progress (conflicts)", parents list has 2 entries

### Manual acceptance

- Create divergent branches with conflicting changes, merge → graph shows dual-parent synthetic row, banner appears.
- Open conflicted files in external editor, resolve, stage in GitStack → conflict indicators disappear.
- Click Continue → merge commit created, graph shows normal merge commit, banner disappears.
- Repeat but click Abort → repo returns to pre-merge state, banner disappears.
- Trigger rebase conflict → banner shows "Rebase in progress", Continue/Abort work.

## File change list

New:
- `tests/presentation/widgets/test_working_tree_banner.py`

Modified:
- `git_gui/domain/ports.py`
- `git_gui/infrastructure/pygit2_repo.py`
- `git_gui/application/queries.py`
- `git_gui/application/commands.py`
- `git_gui/presentation/bus.py`
- `git_gui/presentation/widgets/graph.py`
- `git_gui/presentation/widgets/working_tree.py`
- `git_gui/presentation/main_window.py`

Test files modified:
- `tests/infrastructure/test_reads.py`
- `tests/infrastructure/test_writes.py`
- `tests/application/test_commands.py`
- `tests/application/test_queries.py`
- `tests/presentation/test_graph_model.py`
