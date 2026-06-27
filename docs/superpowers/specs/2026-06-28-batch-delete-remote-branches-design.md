# Batch-delete remote branches — design

**Status:** approved (design)
**Date:** 2026-06-28

## Goal

Let users delete many remote branches at once from a dedicated dialog, instead
of one-at-a-time via the graph/sidebar context menu. Cleanup of stale remote
branches (e.g. merged feature branches, agent worktree branches) should take a
few clicks.

## UX / behavior

- New **"Remote Branches…"** action in the Git menu opens `RemoteBranchesDialog`
  (a sibling to the existing local `BranchesDialog`).
- The dialog lists every remote branch (`get_branches` filtered to `is_remote`,
  excluding `*/HEAD` symbolic refs), one per row with a **checkbox**.
- **Nothing is pre-checked.** The user must explicitly check what to delete.
- Each remote's **default branch** — resolved from `refs/remotes/<remote>/HEAD`
  (e.g. `origin/main`) — is shown but **un-checkable** (disabled), marked
  `(default)` with a tooltip, and excluded from **Select All**.
- A **filter** field (case-insensitive substring) hides non-matching rows.
- **Select All** / **Clear** act only on currently-visible, non-guarded rows.
- **Delete Selected (N)** button: label shows the live count, disabled when 0.
- On click, a **confirmation dialog** lists the selected branches (truncated with
  "+k more" beyond a cap) and the count, warning the action cannot be undone.
- On confirm, deletion runs (see below). When it finishes, a **results summary**
  reports "X deleted, Y failed" with per-branch reasons for failures, and the
  list refreshes (deleted branches disappear).

## Architecture (Clean Architecture)

Dependencies point inward: presentation → application → domain ← infrastructure.

### Domain (`domain/entities.py`, `domain/ports.py`)

- New dataclass `RemoteBranchDeleteResult(branch: str, ok: bool, message: str)`
  where `branch` is the full shorthand (e.g. `origin/feature-a`).
- `IRepositoryReader.remote_default_branches() -> dict[str, str]` — maps remote
  name → default-branch shorthand (e.g. `{"origin": "origin/main"}`). Remotes
  without a resolvable HEAD symref are omitted.
- `IRepositoryWriter.delete_remote_branches(remote: str, branches: list[str]) ->
  list[RemoteBranchDeleteResult]` — `branches` are short names (no remote
  prefix). Returns one result per requested branch.

### Infrastructure (`infrastructure/pygit2/`)

- `branch_ops.remote_default_branches()`: for each remote, resolve
  `refs/remotes/<remote>/HEAD`; if it's a symbolic ref, record the shorthand of
  its target. Skip remotes with no HEAD symref. Read-only; never raises on a
  single bad remote (log + skip), matching `get_branches`.
- `remote_ops.delete_remote_branches(remote, branches)`: run a single
  `git push --porcelain <remote> --delete <ref…>` capturing stdout/stderr, then
  parse the porcelain output into per-branch results.
  - A pure module-level helper `_parse_porcelain_delete(remote, stdout, branches)
    -> list[RemoteBranchDeleteResult]` does the parsing (unit-testable in
    isolation). It is given the requested short `branches`, the `remote`, and the
    porcelain `stdout`, and returns one result per requested branch with
    `branch` set to the full shorthand `f"{remote}/{short}"`.
  - Porcelain delete lines are tab-separated: `<flag>\t<from>:<to>\t<summary>`.
    `flag == "-"` → deleted ok; `flag == "!"` → rejected/error (use `<summary>`
    as the message). The `<to>` ref (`refs/heads/<branch>` or `<branch>`) maps the
    line back to a requested short branch name.
  - If the push produces no parseable per-ref lines (e.g. remote unreachable,
    auth failure), every requested branch is marked failed with the stderr text.
    The method does **not** raise on per-branch rejections — it returns results.

### Application (`application/queries.py`, `application/commands.py`, `presentation/bus.py`)

- `RemoteDefaultBranches` query → `reader.remote_default_branches()`.
- `DeleteRemoteBranches` command → `writer.delete_remote_branches(remote, branches)`.
- Both registered on `QueryBus` / `CommandBus`.

### Presentation (`presentation/dialogs/remote_branches_dialog.py`, `presentation/menus/git_menu.py`)

- `RemoteBranchesDialog(queries, commands, parent)`:
  - `_refresh()` builds the table from `get_branches` + `remote_default_branches`.
  - `_collect_selected() -> list[str]` returns checked, non-guarded full names.
  - `_grouped_by_remote(names) -> dict[str, list[str]]` splits on first `/`.
  - `_perform_deletions(grouped) -> list[RemoteBranchDeleteResult]` calls
    `commands.delete_remote_branches.execute(remote, branches)` once per remote
    and concatenates results. (Synchronous seam; the thread wraps this.)
  - `_on_delete()`: collect → confirm (`QMessageBox`) → run `_perform_deletions`
    in a daemon thread via a `QObject` signals bridge; on `finished(results)`
    (main thread) show the summary and `_refresh()`. Buttons disable while running.
  - Checkbox toggles and filter edits update the Delete button's count/enabled.
- `git_menu.install_git_menu`: add a **"Remote &Branches..."** action that opens
  the dialog (same wiring as the existing Branches action; needs `queries` +
  `commands`).

## Threading

The push is network-bound, so it runs off the UI thread using the codebase's
established pattern (a `QObject` with `finished`/`failed` signals + a daemon
`threading.Thread`), mirroring `_WorktreeOpSignals` / `_RemoteSignals`. The
dialog stays modal; Qt continues to process the bridged signals. Deletion logic
is factored into `_perform_deletions` so tests can exercise it synchronously.

## Testing

- **Infra (`tests/infrastructure/`)**: `_parse_porcelain_delete` against canned
  porcelain — all-ok, mixed ok/rejected (with reason), and empty/total-failure.
- **Application (`tests/application/test_commands.py` etc.)**: `DeleteRemoteBranches`
  and `RemoteDefaultBranches` delegate to the writer/reader.
- **Presentation (`tests/presentation/dialogs/test_remote_branches_dialog.py`,
  qtbot, mocked buses)**: listing excludes `*/HEAD`; default rows are
  un-checkable and skipped by Select All; filter hides non-matching rows; Delete
  button count/enablement; confirmation gate (patched `QMessageBox.question`);
  grouping yields one command call per remote with the right branch lists;
  results summary + refresh. `_perform_deletions` is tested synchronously.

## Out of scope (YAGNI)

- Regex / glob pattern selection (substring filter only).
- "Merged-only" or "stale" detection / auto-selection.
- Deleting local branches (the existing Branches dialog covers that).
- Routing through the main-window remote-op queue (the dialog owns its own
  background thread; acceptable since the dialog is modal).
