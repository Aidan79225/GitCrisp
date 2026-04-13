# Interactive Rebase (Phase 1) — Design

**Status:** Draft
**Date:** 2026-04-13
**Scope:** Phase 1 — pick/squash/fixup/drop + reorder. No reword or edit pauses.

## Background

GitStack currently supports only non-interactive rebase (`git rebase <target>` via subprocess). Users who want to squash, reorder, or drop commits must use the CLI. Interactive rebase is one of the most-requested power-user features in any git GUI.

This spec adds a commit list editor dialog triggered from the graph context menu. The user selects actions (pick/squash/fixup/drop) and reorders commits, then the tool generates a `git-rebase-todo` and runs `git rebase -i` with a custom `GIT_SEQUENCE_EDITOR`.

## Goals

- Let users squash, fixup, drop, and reorder commits from the GUI.
- Integrate naturally with the existing graph context menu and the Spec C conflict resolution flow.
- Keep Phase 1 focused: no reword (edit commit message mid-rebase) or edit (pause to amend) actions.

Out of scope (Phase 2 / follow-up):
- Reword action (pause to edit message)
- Edit action (pause to amend commit)
- Autosquash (`--autosquash`)
- `fixup -C` / `fixup -c` variants

## Entry Point

New context menu entries in the graph's merge/rebase submenu (`_add_merge_rebase_section` in `graph.py`):

- For branch targets: `"Interactive rebase onto {branch}"` — appears alongside the existing `"Rebase {H} onto {branch}"`.
- For commit targets: `"Interactive rebase onto commit {short_oid}"`.
- Same disable rules as existing rebase entries (DETACHED_HEAD, non-CLEAN repo state).

New signals on `GraphWidget`:
- `interactive_rebase_branch_requested = Signal(str)` — branch name
- `interactive_rebase_commit_requested = Signal(str)` — oid

## InteractiveRebaseDialog

**File:** `git_gui/presentation/dialogs/interactive_rebase_dialog.py`

A modal `QDialog` opened by the main window handler.

### Constructor

```
InteractiveRebaseDialog(
    commits: list[Commit],   # oldest-first
    target_label: str,       # e.g. "main" or "commit abc1234"
    parent=None,
)
```

### Layout

- **Title bar:** "Interactive Rebase onto {target_label}"
- **Table** (`QTableWidget`):
  - Columns: Action, OID, Message
  - Action column: `QComboBox` per row with options: pick, squash, fixup, drop. Default: pick.
  - OID column: read-only `QTableWidgetItem` showing the short (7-char) oid.
  - Message column: read-only `QTableWidgetItem` showing the first line of the commit message.
  - Rows: one per commit, **oldest first** (the commit at the top is the first to be replayed).
  - Drag-and-drop reorderable: `setDragDropMode(QAbstractItemView.InternalMove)`, `setSelectionBehavior(QAbstractItemView.SelectRows)`, `setDragDropOverwriteMode(False)`.
- **Buttons:** "Execute" (primary, accepts dialog) + "Cancel" (rejects dialog).
- **Validation:** "Execute" is disabled when squash or fixup is the action on the first row (no preceding commit to squash into). Tooltip on the disabled button: "Cannot squash/fixup the first commit — no preceding commit to combine with."

### Return value

`result_entries() -> list[tuple[str, str]]` — returns a list of `(action, oid)` tuples in the (possibly reordered) row order. Actions are the strings `"pick"`, `"squash"`, `"fixup"`, `"drop"`.

## Execution Engine

### Infrastructure: `interactive_rebase(target_oid, entries)`

**Method on `Pygit2Repository`:**

1. Write a temp file containing the todo:
   ```
   pick abc1234
   squash def5678
   fixup 789abcd
   drop 0123456
   ```
   Each line is `{action} {full_oid}` (git accepts both short and full oids, but full is safer).

2. Set environment:
   - `GIT_SEQUENCE_EDITOR` = a Python one-liner that copies the temp file over the editor target: `python -c "import shutil,sys; shutil.copy('<temp_path>', sys.argv[1])"`.
   - Also include `self._git_env` (GIT_DIR + GIT_WORK_TREE) for submodule correctness.

3. Run `git rebase -i <target_oid>`.

4. Clean up the temp file in a `finally` block.

5. If exit code != 0:
   - Check repo state: if REBASING, it's a conflict → don't raise, let the banner handle it.
   - Otherwise raise `RuntimeError` with stderr.

### Infrastructure: `get_commit_range(head_oid, base_oid)`

Walk from `head_oid` back to `base_oid` (exclusive) using `self._repo.walk(head_oid, TOPOLOGICAL | TIME)`. Collect commits until we find `base_oid`, then reverse to get oldest-first. Return as `list[Commit]`.

If `base_oid` is not an ancestor of `head_oid`, return an empty list (the dialog won't open).

### Application layer

- `GetCommitRange` query: wraps `reader.get_commit_range(head_oid, base_oid)`.
- `InteractiveRebase` command: wraps `writer.interactive_rebase(target_oid, entries)`.

### Bus

Wire both into `QueryBus` and `CommandBus`.

### Main window handler

For `interactive_rebase_branch_requested(branch_name)`:
1. Resolve branch to oid via `GetBranches`.
2. Get HEAD oid via `GetHeadOid`.
3. Fetch commit range via `GetCommitRange(head_oid, branch_target_oid)`.
4. If empty → log "No commits to rebase" and return.
5. Open `InteractiveRebaseDialog(commits, branch_name)`.
6. If accepted → run `InteractiveRebase(branch_target_oid, dialog.result_entries())` as a remote op (threaded, with status bar).
7. Reload on success. On conflict, Spec C banner appears automatically.

For `interactive_rebase_commit_requested(oid)`: same flow, with `oid` as target and `commit {short_oid}` as label.

## Testing

### Infrastructure

`tests/infrastructure/test_reads.py`:
- `test_get_commit_range_returns_oldest_first` — 3 commits A→B→C, range from C to A returns [B] (A excluded, C excluded since C is HEAD and range is between HEAD and base).

  Actually: `get_commit_range(head_oid=C, base_oid=A)` walks from C, collects B (stops before A), reverses → [B]. Wait — we also need C itself if we're rebasing commits on top of A. Let me clarify: `git rebase -i A` when HEAD is C would show B and C in the todo. So `get_commit_range` should collect commits from HEAD back to base (exclusive), including HEAD itself. Walk collects C, B, stops at A. Reverse → [B, C].

`tests/infrastructure/test_writes.py`:
- `test_interactive_rebase_squash` — create 3 commits on a branch, squash the last two into one, verify the result has 2 commits total and the squashed commit contains both changes.

### Application

`tests/application/test_queries.py`: `GetCommitRange` passthrough.
`tests/application/test_commands.py`: `InteractiveRebase` passthrough.

### Dialog (pytest-qt)

`tests/presentation/dialogs/test_interactive_rebase_dialog.py`:
- `test_default_action_is_pick` — all rows default to "pick".
- `test_rows_match_commit_count` — dialog with 3 commits → 3 rows.
- `test_commit_order_is_oldest_first` — first row's oid matches the oldest commit.
- `test_squash_on_first_row_disables_execute` — set first row to "squash" → Execute button disabled.
- `test_result_entries_returns_actions_and_oids` — change some actions, call `result_entries()`, verify output.

## File change list

New:
- `git_gui/presentation/dialogs/interactive_rebase_dialog.py`
- `tests/presentation/dialogs/test_interactive_rebase_dialog.py`

Modified:
- `git_gui/domain/ports.py`
- `git_gui/infrastructure/pygit2_repo.py`
- `git_gui/application/queries.py`
- `git_gui/application/commands.py`
- `git_gui/presentation/bus.py`
- `git_gui/presentation/widgets/graph.py`
- `git_gui/presentation/main_window.py`

Test files modified:
- `tests/infrastructure/test_reads.py`
- `tests/infrastructure/test_writes.py`
- `tests/application/test_queries.py`
- `tests/application/test_commands.py`
