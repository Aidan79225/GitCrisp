# Sidebar double-click checkout + Stash identity prompt — design

Two related UX paper-cuts:

1. **Double-clicking a remote branch in the sidebar does nothing.** Users expect it to checkout, like the graph context menu does. Local-branch double-click already works but goes through a code path that lacks error handling, logging, and reload coordination.
2. **`git stash` fails when `user.name`/`user.email` is unset.** Commit already prompts via the identity dialog; stash should too. Same hole likely affects tag, cherry-pick, revert, and merge — but those are out of scope here.

## Goals

- Double-click on either a local or remote branch in the sidebar produces the same behavior as the graph context menu's "Checkout branch" action, including the "local already exists — reset?" conflict prompt.
- Stash prompts for identity before running when `user.name`/`user.email` is missing, identically to commit.
- A reusable `ensure_identity` helper is available for future flows (tag, cherry-pick, revert, merge) without further refactoring.

## Non-goals

- Wiring `ensure_identity` into tag, cherry-pick, revert, or merge flows (separate PRs).
- Changing the conflict prompt's text or behavior.
- Changing the identity dialog itself.

## Architecture

### Feature 1: Unified branch checkout flow

Today, "checkout a branch" has two implementations:

| Trigger | Path |
|---|---|
| Sidebar double-click (local) | `commands.checkout.execute(value)` direct + `branch_checkout_requested` notification signal |
| Sidebar right-click "Checkout" | Same as above |
| Sidebar double-click (remote) | (nothing — bug) |
| Graph context menu "Checkout branch: …" | `checkout_branch_requested` signal → `_on_checkout_branch` handler |

The graph path is the better one: try/except, log panel expansion on error, conflict prompt when a same-named local branch exists, and full reload at the end. The fix is to **route every sidebar checkout through the same handler.**

**Sidebar changes (`git_gui/presentation/widgets/sidebar.py`):**

- Add `checkout_branch_requested = Signal(str)` (mirrors `graph.checkout_branch_requested`).
- `_on_double_click`: handle both `kind == "branch"` and `kind == "remote_branch"`; both emit `checkout_branch_requested.emit(value)`. Remove the direct `commands.checkout.execute(value)` call.
- Right-click "Checkout" menu action: emit `checkout_branch_requested.emit(value)` instead of the direct call.
- Remove the old `branch_checkout_requested` signal (now no listeners).

**Main-window changes (`git_gui/presentation/main_window/branch_flows.py`):**

- `_wire_branch_flow_signals`: replace the `branch_checkout_requested → _on_branch_changed` wiring with `sidebar.checkout_branch_requested → _on_checkout_branch`.
- Delete the `_on_branch_changed` method.
- Verify `_on_checkout_branch`'s end-of-flow `self._reload()` produces the same observable effect as the old `_on_branch_changed` (sidebar reload + graph reload that scrolls to HEAD). If `_reload()` doesn't already cover scroll-to-HEAD after a checkout, fold that behavior in.

The `_on_checkout_branch` body itself is unchanged — it already handles the conflict prompt correctly (fixed in PR #70).

### Feature 2: Reusable `ensure_identity` helper

Today, `working_tree.py:_ensure_identity` is a private method on the working-tree widget. It checks `queries.get_identity`, shows `IdentityDialog`, calls `commands.set_identity` on confirm, and emits the widget-specific `commit_failed` signal on cancel/save-error.

The check + dialog + save flow has no widget-specific state — it can be a free function.

**New helper (`git_gui/presentation/dialogs/identity_dialog.py`):**

```python
def ensure_identity(
    parent: QWidget,
    queries: QueryBus,
    commands: CommandBus,
) -> bool:
    """Prompt for git identity if not yet configured.

    Returns True if identity is already set, or the user successfully
    set it via the dialog. Returns False if the user cancelled or
    saving failed (the caller is responsible for any error messaging).
    """
```

**Caller changes:**

- `working_tree._ensure_identity` becomes a thin wrapper: call `ensure_identity(self, self._queries, self._commands)`; on `False`, emit `commit_failed("Failed to save identity")` or stay silent on cancel (preserve current behavior — cancel is silent, save-error already emits).
- `stash_flows._on_stash_requested`: call `ensure_identity(self, self._queries, self._commands)` at the top; if `False`, return without logging an error (consistent with how commit silently aborts on identity-dialog cancel).

## Data flow

### Checkout path after refactor

```
User double-clicks branch in sidebar
  │
  ▼
sidebar._on_double_click → emit checkout_branch_requested(name)
  │
  ▼
main_window._on_checkout_branch(name)
  │ get_branches → classify local vs remote
  │ if conflict: QMessageBox.question (Yes resets, Cancel aborts)
  │ else: checkout / checkout_remote_branch
  ▼
self._reload() — sidebar + graph
```

### Stash path after refactor

```
User clicks Stash button in graph header
  │
  ▼
stash_flows._on_stash_requested
  │
  ▼
ensure_identity(self, queries, commands)
  │ identity set? → True
  │ user cancels dialog? → False (return early, no log)
  │ user fills + saves? → set_identity.execute → True
  ▼
commands.stash.execute(f"WIP on {branch}")
  │ on exception → log_error
  ▼
self._reload()
```

## Error handling

- Sidebar checkout: handled by `_on_checkout_branch` (already implemented). Exceptions log to the log panel and expand it; `_reload` always runs.
- Identity helper: never raises. Cancel returns `False` silently. Save errors return `False` (caller decides messaging).
- Stash identity-cancel: silent abort, no log entry (matches commit's silent-cancel behavior).
- Stash itself: existing try/except in `_on_stash_requested` unchanged.

## Testing

### Feature 1 — extend `tests/presentation/test_main_window_checkout_conflict.py`

| Scenario | Expectation |
|---|---|
| Sidebar double-click local `feature/foo` | `_on_checkout_branch` runs; `checkout.execute("feature/foo")` called |
| Sidebar double-click remote `origin/foo`, no local | `checkout_remote_branch.execute("origin/foo")` called |
| Sidebar double-click remote `origin/foo`, local `foo` exists, user confirms | `checkout` + `reset_branch_to_ref` called |
| Sidebar double-click remote `origin/foo`, local `foo` exists, user cancels | Neither called |

These can reuse the existing `_wire_buses` fixture by invoking `win._on_checkout_branch` directly — sidebar's signal goes nowhere meaningful in tests; we test the handler.

A separate small test for the sidebar layer (extend `tests/presentation/widgets/test_sidebar_signals.py`) confirms double-click emits the new signal — pure widget test, no main-window.

### Feature 2 — new `tests/presentation/test_stash_identity_prompt.py`

| Scenario | Expectation |
|---|---|
| Identity already set | `ensure_identity` returns True without showing dialog; `stash.execute` called |
| Identity missing, user cancels dialog | Dialog shown; `stash.execute` NOT called; no error log |
| Identity missing, user fills + saves | `set_identity.execute` called; `stash.execute` called |

Identity-helper unit tests (extend `tests/presentation/dialogs/test_identity_dialog.py`): cover the helper in isolation by patching `IdentityDialog.exec`.

## Edge cases

- **Multi-slash remote names** (`origin/release/2025-04`): already handled — `_on_checkout_branch` uses `name.split("/", 1)` to derive the local-name candidate.
- **Empty repo / no HEAD**: identity prompt still works (`get_identity` reads from gitconfig, not refs).
- **Race: user changes identity in another process between check and stash**: not handled; `stash.execute` would still error, which is fine — that's the existing path.
- **`branch` kind with no value in sidebar model**: `_on_double_click` already guards via `if kind == "branch"`; the new code mirrors that guard for `remote_branch`.

## File diff summary

| File | Change |
|---|---|
| `git_gui/presentation/widgets/sidebar.py` | Add `checkout_branch_requested` signal; rewrite double-click + right-click "Checkout" to emit it; remove `branch_checkout_requested`. |
| `git_gui/presentation/main_window/branch_flows.py` | Rewire to `_on_checkout_branch`; delete `_on_branch_changed`. |
| `git_gui/presentation/dialogs/identity_dialog.py` | New free function `ensure_identity`. |
| `git_gui/presentation/widgets/working_tree.py` | `_ensure_identity` becomes a thin wrapper. |
| `git_gui/presentation/main_window/stash_flows.py` | Call `ensure_identity` before `stash.execute`. |
| `tests/presentation/test_main_window_checkout_conflict.py` | Four new test cases for sidebar double-click paths. |
| `tests/presentation/widgets/test_sidebar_signals.py` | Extend: confirm sidebar emits `checkout_branch_requested` on double-click + right-click "Checkout". |
| `tests/presentation/dialogs/test_identity_dialog.py` | Extend: unit tests for the new `ensure_identity` helper. |
| `tests/presentation/test_stash_identity_prompt.py` | New: stash flow integration. |

Net: 5 source files changed, 4 test files changed or added. No new dependencies.
