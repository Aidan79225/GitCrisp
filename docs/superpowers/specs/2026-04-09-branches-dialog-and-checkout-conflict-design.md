# Branches Dialog and Checkout-Conflict Dialog

**Date:** 2026-04-09
**Status:** Approved

## Overview

Two related branch-management features:

1. **Branches dialog** — a new `Git → Branches...` menubar item opens a dialog listing local branches with their upstream tracking. Supports checkout, create, rename, set/unset upstream, and delete.
2. **Checkout-conflict dialog** — when checking out a remote branch (e.g. `origin/feature`) that has a same-named local branch, prompt the user. On confirmation, hard-reset the local branch to the remote HEAD; on cancel, abort.

A local git branch has at most one upstream (per `branch.<name>.remote` + `branch.<name>.merge` config), so the dialog uses a single upstream column per row.

## Architecture

Follows the existing clean-architecture stack (domain → application → infrastructure → presentation) and mirrors the `RemoteDialog` / `SubmoduleDialog` pattern. All branch operations use pygit2 directly — no subprocess wrappers needed.

### New files

- `git_gui/presentation/dialogs/branches_dialog.py` — `BranchesDialog(QDialog)` plus small helper modals.
- `tests/presentation/dialogs/test_branches_dialog.py`
- `tests/infrastructure/test_pygit2_repo_branches.py`

### Modified files

- `git_gui/domain/entities.py` — add `LocalBranchInfo` dataclass.
- `git_gui/domain/ports.py`:
  - Reader: `list_local_branches_with_upstream() -> list[LocalBranchInfo]`
  - Writer: `set_branch_upstream`, `unset_branch_upstream`, `rename_branch`, `reset_branch_to_ref`
- `git_gui/application/queries.py` — `ListLocalBranchesWithUpstream`.
- `git_gui/application/commands.py` — `SetBranchUpstream`, `UnsetBranchUpstream`, `RenameBranch`, `ResetBranchToRef`.
- `git_gui/presentation/bus.py` — register the new query/commands.
- `git_gui/infrastructure/pygit2_repo.py` — implement the new methods.
- `git_gui/presentation/menus/git_menu.py` — add `&Branches...` action between `&Remotes...` and `&Submodules...`.
- `git_gui/presentation/main_window.py` — wrap `_on_checkout_branch` to handle the conflict case.

## Domain Entity

```python
@dataclass
class LocalBranchInfo:
    name: str
    upstream: str | None
    last_commit_sha: str
    last_commit_message: str
```

## Branches Dialog

### Layout

```
┌─ Branches ─────────────────────────────────────────────────┐
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Name        │ Upstream         │ Last commit         │  │
│  │ master      │ origin/master    │ a1b2c3d  fix: ...   │  │
│  │ feature/foo │ origin/feature/.. │ 9f8e7d6  feat: ... │  │
│  │ wip         │ (none)           │ 4e2d1c0  WIP        │  │
│  └──────────────────────────────────────────────────────┘  │
│  [Checkout] [Create...] [Rename...] [Set Upstream...]     │
│  [Delete]                                                  │
│                                              [ Close ]    │
└────────────────────────────────────────────────────────────┘
```

Columns: **Name**, **Upstream** (`(none)` if unset), **Last commit** (short SHA + first line of message). Single-select.

### Operations

- **Checkout** — `commands.checkout.execute(name)`. Closes the dialog after success so the user lands in the new state.
- **Create...** — modal asking `Name` + `Start point` (defaults to the currently selected row's branch). Calls `create_branch` then `checkout`.
- **Rename...** — modal with new name. Calls `rename_branch(old, new)`.
- **Set Upstream...** — modal with a `QComboBox` listing all remote branches (from `get_branches()` filtered by `is_remote`) plus a `(none)` option. OK calls `set_branch_upstream(name, "origin/foo")` or `unset_branch_upstream(name)` for `(none)`.
- **Delete** — confirm dialog, then `delete_branch(name)`. Disabled when the selected row is HEAD.

### Refresh & errors

After every mutation, re-query `list_local_branches_with_upstream` and rebuild the table. All port calls are wrapped in `try/except Exception as e:`; errors are surfaced via `QMessageBox.warning(self, "<Operation> failed", str(e))` and the dialog stays open. Only Checkout closes the dialog on success.

## Checkout-Conflict Dialog

### Trigger

`MainWindow._on_checkout_branch(name)` currently distinguishes remote vs local by `"/" in name` (the historical convention in this widget — remote branches arrive prefixed with the remote name, e.g. `origin/feature`). When the name is a remote branch, strip the remote prefix to get the local name and check whether that local already exists.

### Logic

```python
def _on_checkout_branch(self, name: str) -> None:
    if "/" in name:  # remote branch
        local_name = name.split("/", 1)[1]
        existing = {b.name for b in self._queries.get_branches.execute()
                    if not b.is_remote}
        if local_name in existing:
            reply = QMessageBox.question(
                self,
                "Local branch exists",
                f"Local branch '{local_name}' already exists.\n\n"
                f"Reset it to '{name}' (HEAD)? This discards any local commits "
                f"and uncommitted changes on '{local_name}'.",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if reply != QMessageBox.Yes:
                return
            try:
                self._commands.checkout.execute(local_name)
                self._commands.reset_branch_to_ref.execute(local_name, name)
                self._log_panel.log(f"Reset {local_name} to {name}")
            except Exception as e:
                self._log_panel.expand()
                self._log_panel.log_error(
                    f"Reset {local_name} → {name} ERROR: {e}"
                )
            self._reload()
            return
    # ...existing flow unchanged for non-conflict cases
```

### Why two operations (`checkout` then `reset_branch_to_ref`)

Keeps `reset_branch_to_ref` a generic writer method (potentially reusable from the Branches dialog later). It hard-resets the currently checked-out branch to the given ref via pygit2's `repo.reset(target_oid, pygit2.GIT_RESET_HARD)`.

### Edge cases

- `local_name` does not exist → fall through to the existing `checkout_remote_branch` flow (current behavior, unchanged).
- Uncommitted changes on `local_name` → the warning text already says "discards uncommitted changes". The hard reset blows them away. No second prompt.
- Remote branch with multiple slashes (e.g. `origin/feature/foo`) → `name.split("/", 1)[1]` correctly yields `feature/foo`.

## Application Layer

New query class:

```python
class ListLocalBranchesWithUpstream:
    def __init__(self, reader): self._reader = reader
    def execute(self): return self._reader.list_local_branches_with_upstream()
```

New command classes (each delegates to the corresponding writer method):
`SetBranchUpstream`, `UnsetBranchUpstream`, `RenameBranch`, `ResetBranchToRef`.

## Infrastructure Notes (pygit2)

- **`list_local_branches_with_upstream`**: iterate `repo.branches.local`. For each, read `branch.upstream` (a `Branch` or `None`); upstream display name is `branch.upstream.shorthand` or `None`. Last commit is the branch's `peel(Commit)` — short sha + first line of message.
- **`set_branch_upstream(name, upstream)`**: set `repo.branches.local[name].upstream = repo.branches.remote[upstream]`.
- **`unset_branch_upstream(name)`**: set `repo.branches.local[name].upstream = None`.
- **`rename_branch(old, new)`**: `repo.branches.local[old].rename(new)`.
- **`reset_branch_to_ref(branch, ref)`**: resolve `ref` to an oid (`repo.revparse_single(ref).id`) and call `repo.reset(oid, pygit2.GIT_RESET_HARD)`. Caller is responsible for ensuring `branch` is currently checked out (the Checkout-Conflict flow does this in two steps: `checkout(local_name)` then `reset_branch_to_ref(local_name, ref)`).

## Menu Wiring

`git_menu.py` adds a third action `&Branches...` between `&Remotes...` and `&Submodules...`. The handler constructs a `BranchesDialog(queries, commands, window)` and `exec()`s it. Disabled (no-op) when buses are `None`.

## Testing

- **Domain** — `tests/domain/test_entities_branch_info.py`: trivial dataclass shape test.
- **Application** — `tests/application/test_commands_branches.py` and `tests/application/test_queries_branches.py`: MagicMock the writer/reader, verify the right port methods are called with the right args.
- **Infrastructure** — `tests/infrastructure/test_pygit2_repo_branches.py`: build a real temp git repo with two branches and a fake "remote" (a second local repo or a manual `branch.<name>.remote = .` config). Cover: list returns `(none)` initially, set/unset upstream round-trip, rename, reset hard.
- **Dialog** — `tests/presentation/dialogs/test_branches_dialog.py`: pytest-qt + MagicMock buses. Verify table populates from query; Delete/Rename/SetUpstream call the right command with the right args; error path shows `QMessageBox.warning`.
- **Main window conflict** — extend or create a small main_window test that mocks `get_branches` to include both `feature` (local) and `origin/feature` (remote). One test patches `QMessageBox.question` → `Yes` and verifies `checkout` + `reset_branch_to_ref` are both called; another patches → `Cancel` and verifies neither is called.

All Python operations run via `uv run` per `CLAUDE.md`.

## Out of Scope (YAGNI)

- Multi-select bulk delete.
- Force-delete (`-D`) for unmerged branches.
- Reflog / per-branch history view.
- Showing remote branches in the dialog (the graph already lists them).
- Ahead/behind tracking counts.
- HEAD-marker column.
- Background threading.
- A standalone "Reset to..." entry in the Branches dialog (we add the writer method but don't expose a button — only the conflict flow uses it).
