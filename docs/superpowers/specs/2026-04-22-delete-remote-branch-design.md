# Delete Remote Branch — Design

**Date:** 2026-04-22
**Status:** Proposed

## Goal

Add a sidebar context-menu action to delete a remote branch. Follows the existing `delete_remote_tag` end-to-end pattern. Scope is remote-only; local branch deletion stays on its own menu item.

## Scope

- Infrastructure: `delete_remote_branch(remote, branch)` on `BranchOps` via `git push <remote> --delete <branch>`.
- Domain port: add the method to `IRepositoryWriter`.
- Application command: `DeleteRemoteBranch`, registered on `CommandBus`.
- Presentation: new sidebar signal + Delete menu item on remote-branch rows; confirm dialog + remote-op-queue handling in `BranchFlowsMixin`.
- Two regression tests covering menu emission (single-slash and multi-slash branch names).

Not in scope:
- Combined local + remote delete.
- `--force` / unmerged-commits protection.
- Auto-cleanup of the local tracking branch.
- README update (the "Delete" menu reads naturally as an extension of existing context-menu behaviour).

## UX Decisions

| Concern | Decision |
|---|---|
| Trigger | Right-click a remote-branch row (e.g. `origin/feature`) in the sidebar → Delete. |
| Confirm | `QMessageBox.question` with "Delete remote branch `{remote}/{branch}`? This cannot be undone." |
| Execution | Serialized through the existing `_run_remote_op` queue on `RemoteOpQueueMixin`. |
| Success feedback | Log line in `LogPanel` via the existing `_on_remote_done` handler. Next auto-reload (from the change detector's `refs/remotes/` watch) brings the sidebar tree up to date. |
| Failure feedback | Log error via the existing `_on_remote_error` handler. |
| Force delete | Not offered in v1. `git push --delete` without `--force` is the safe default. |
| Branch-name parsing | `value.split("/", 1)` — remote names don't contain `/`; branch names may. |

## Architecture & files touched

**Modified files:**

```
git_gui/infrastructure/pygit2/branch_ops.py   # add delete_remote_branch method
git_gui/domain/ports.py                        # add to IRepositoryWriter
git_gui/application/commands.py                # add DeleteRemoteBranch class
git_gui/presentation/bus.py                    # register command on CommandBus
git_gui/presentation/widgets/sidebar.py        # new signal + menu action
git_gui/presentation/main_window/branch_flows.py  # handler + wiring
```

**Modified tests:**

```
tests/presentation/widgets/test_sidebar_signals.py   # two new emission tests
```

Total: ~100 LOC of implementation, ~30 LOC of tests across 7 files.

## Implementation details

### `pygit2/branch_ops.py` — new method

```python
def delete_remote_branch(self, remote: str, branch: str) -> None:
    """Delete a branch on the remote via `git push <remote> --delete <branch>`."""
    self._run_git("push", remote, "--delete", branch)
```

Place immediately after `delete_branch`. `self._run_git` resolves via MRO to `RemoteOps`.

### `domain/ports.py` — port addition

On `IRepositoryWriter`, alongside the existing `delete_remote_tag`:

```python
def delete_remote_branch(self, remote: str, branch: str) -> None: ...
```

### `application/commands.py` — new command

```python
class DeleteRemoteBranch:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, remote: str, branch: str) -> None:
        self._writer.delete_remote_branch(remote, branch)
```

### `presentation/bus.py` — command bus wiring

Add the import, add the attribute to `CommandBus`, instantiate in `CommandBus.from_writer`. Same shape as `delete_remote_tag`.

### `presentation/widgets/sidebar.py` — signal + menu action

Add the signal alongside the existing branch / tag signals:

```python
remote_branch_delete_requested = Signal(str, str)  # (remote, branch)
```

In `_show_context_menu`, inside the `kind == "remote_branch"` branch, extend the menu so it reads:

```python
elif kind == "remote_branch":
    remote, branch = value.split("/", 1)
    menu.addAction("Fetch").triggered.connect(
        lambda: self.fetch_requested.emit(remote))
    menu.addSeparator()
    menu.addAction("Delete").triggered.connect(
        lambda: self.remote_branch_delete_requested.emit(remote, branch))
```

The existing Fetch action already does `remote = value.split("/")[0]` on the fly — both forms resolve identically for a simple `origin/feature` name. Using `split("/", 1)` and binding both `remote` and `branch` once at menu-build time is clearer and supports branch names that contain `/` (e.g. `feature/foo`).

### `presentation/main_window/branch_flows.py` — handler + wiring

In `_wire_branch_flow_signals`, add:

```python
self._sidebar.remote_branch_delete_requested.connect(self._on_delete_remote_branch)
```

Add the handler:

```python
def _on_delete_remote_branch(self, remote: str, branch: str) -> None:
    reply = QMessageBox.question(
        self,
        "Delete Remote Branch",
        f"Delete remote branch `{remote}/{branch}`? This cannot be undone.",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if reply != QMessageBox.Yes:
        return
    self._run_remote_op(
        f"Delete {remote}/{branch}",
        lambda: self._commands.delete_remote_branch.execute(remote, branch),
    )
```

`QMessageBox` is already imported in `branch_flows.py`. `self._run_remote_op` resolves via MRO to `RemoteOpQueueMixin`.

## Testing

**`tests/presentation/widgets/test_sidebar_signals.py`** — add two tests after the existing context-menu tests:

```python
def test_remote_branch_delete_menu_emits_remote_and_branch(sidebar, qtbot):
    w, _, _ = sidebar
    item = _remote_branch_item("origin/feature", "abc123")
    _add_section(w, "REMOTE BRANCHES", [item])

    actions = _capture_menu_actions(w, item)
    assert "Delete" in actions

    with qtbot.waitSignal(w.remote_branch_delete_requested, timeout=1000) as blocker:
        actions["Delete"].trigger()
    assert blocker.args == ["origin", "feature"]


def test_remote_branch_delete_handles_slash_in_branch_name(sidebar, qtbot):
    """Branch names containing '/' must be preserved after splitting off
    the remote prefix (e.g. origin/feature/foo → remote=origin, branch=feature/foo)."""
    w, _, _ = sidebar
    item = _remote_branch_item("origin/feature/foo", "abc123")
    _add_section(w, "REMOTE BRANCHES", [item])

    actions = _capture_menu_actions(w, item)

    with qtbot.waitSignal(w.remote_branch_delete_requested, timeout=1000) as blocker:
        actions["Delete"].trigger()
    assert blocker.args == ["origin", "feature/foo"]
```

The existing `_capture_menu_actions` helper already swaps in `_NoExecMenu` so no stray menu windows will pop up.

No tests for the infrastructure subprocess call — matches how `delete_remote_tag` landed (thin `_run_git` wrapper).

No test for the `BranchFlowsMixin._on_delete_remote_branch` handler — the mixin integration is visually confirmable against the established `_on_delete_branch` pattern.

## Error handling

- `git push --delete` on a missing branch: raises `subprocess.CalledProcessError`; the existing remote-op-queue handler (`_on_remote_error`) logs the error and surfaces it in the log panel. No extra handling needed.
- Network failure: same path; logged by existing handler.
- User confirms but the remote op fails: no rollback needed (nothing was changed locally).

## Out of scope

- Combined local + remote delete (a follow-up feature if needed).
- `--force` push for non-fast-forward remote branches.
- Auto-cleanup of the local tracking branch after remote delete.
- Undo / reversal after deletion.
- Unmerged-commits warning before deletion.
- README update.
- Any changes to the graph context menu (the delete action lives only on the sidebar's remote-branch rows).
