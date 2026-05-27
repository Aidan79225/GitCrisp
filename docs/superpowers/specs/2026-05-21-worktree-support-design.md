# Worktree Support — Design

**Date:** 2026-05-21
**Status:** Proposed

## Goal

Add first-class `git worktree` support to GitCrisp at parity with best-in-class GUI clients (Tower, Fork, GitKraken, IntelliJ). Users can list, create, switch between, lock/unlock, and remove worktrees from inside GitCrisp without dropping to a terminal. Smart-checkout removes the most common friction by transparently switching to an already-owning worktree instead of erroring.

Non-goals for v1: post-create hooks (env-file copy, setup commands), default-path templating beyond a single sensible default, change migration between worktrees, bare-repo-as-primary workflows, cross-worktree diff. Those are interesting differentiators but live outside baseline parity and become follow-ups.

## Scope

- **List, add, remove, lock/unlock** worktrees of the active repo.
- **Sidebar integration**: worktrees nest under their parent repo in the existing multi-repo sidebar, mirroring the submodule pattern.
- **Add Worktree dialog**: single MD3 dialog with branch combo, optional "create new branch" toggle, base-ref picker, and live-templated default path.
- **Smart checkout**: when the user checks out a branch already checked out in another worktree, auto-switch to that worktree and show a status-bar toast instead of surfacing git's error.
- **Two-stage remove**: plain confirm → detect dirty/locked → explicit force prompt.
- **Worktree-aware branch indicator**: branches checked out in a worktree get a `+` badge in the branches sidebar and Branches dialog.
- **Auto-refresh integration**: extend `RepoChangeDetector` to pick up `.git/worktrees/` mutations.

## UX Decisions

| Concern | Decision |
|---|---|
| Switching model | Worktrees nested under parent repo in the multi-repo sidebar (like submodules). Clicking switches the whole window's repo context. |
| Default new-worktree path | `{repo_parent}/{repo_name}-{sanitized_branch}` (Lazygit pattern). User can edit before confirming. |
| Create dialog shape | Single dialog: branch combo + "Create new branch" checkbox. Branches already in another worktree disabled with "switch instead" link. |
| Smart checkout | Auto-switch to the owning worktree on "already checked out" error. Status-bar toast notifies the user. |
| Removal | Two-stage: plain confirm first; if git refuses with `is dirty` / `is locked`, second dialog shows what was found + Force / Cancel. |
| Visual marker on branches | Small `+` badge on branches that own a worktree, in sidebar branch tree and Branches dialog. Tower-style. |
| Lock surfacing | Lock icon on locked worktree rows; tooltip shows lock reason. |
| Theming | Strict MD3: all colors via `presentation/theme/tokens.py` role tokens; dialog uses MD3 elevation/shape; icons use the existing MD3 icon family. No hard-coded hex. |

## Approach

Add one entity, two query/command pairs, one infrastructure mixin, one CLI wrapper, and two dialogs. Wrap the existing checkout call path with a smart-switch interceptor. Extend `RepoChangeDetector`'s watched-path list. Reuse `RepoLifecycleMixin` for the actual repo-context switch — a worktree is just another repo path to open.

## Architecture & files touched

**New files:**
```
git_gui/infrastructure/
├── worktree_cli.py                        # subprocess wrapper for `git worktree remove [--force]`
└── pygit2/
    └── worktree_ops.py                    # WorktreeOpsMixin: list / add / lookup / lock / unlock / find_for_branch

git_gui/presentation/dialogs/
├── add_worktree.py                        # Add Worktree dialog
└── worktrees.py                           # Manage Worktrees dialog (list view)

tests/infrastructure/pygit2/
└── test_worktree_ops.py

tests/infrastructure/
└── test_worktree_cli.py

tests/application/
└── test_worktree_commands.py

tests/presentation/dialogs/
├── test_add_worktree_dialog.py
└── test_worktrees_dialog.py

tests/presentation/
├── test_sidebar_worktrees.py
├── test_smart_checkout.py
└── test_remove_worktree_flow.py
```

**Modified files:**
- `git_gui/domain/entities.py` — add `Worktree` dataclass.
- `git_gui/domain/ports.py` — add `list_worktrees`, `find_worktree_for_branch` on `IRepositoryReader`; `add_worktree`, `remove_worktree`, `lock_worktree`, `unlock_worktree` on `IRepositoryWriter`.
- `git_gui/application/queries.py` — `ListWorktrees`, `FindWorktreeForBranch`.
- `git_gui/application/commands.py` — `AddWorktree`, `RemoveWorktree`, `LockWorktree`, `UnlockWorktree`.
- `git_gui/infrastructure/pygit2/repository.py` — include `WorktreeOpsMixin` in the composite.
- `git_gui/presentation/bus.py` — register new commands/queries.
- `git_gui/presentation/main_window/` — wire smart-checkout interceptor around existing checkout calls; pass worktree list into the repo sidebar on repo load.
- `git_gui/presentation/widgets/repo_list.py` — render worktree child rows under parent repo rows: two-line entries (branch / `~`-relative path), active-row indicator, lock icon, context menu items (Open / Lock / Unlock / Remove). Parent-row context menu gains Add Worktree… and Manage Worktrees….
- `git_gui/presentation/widgets/sidebar.py` — render `+` badge on branch rows that own a worktree; add "Checkout in New Worktree…" to branch context menu.
- `git_gui/presentation/widgets/graph.py` — add "Checkout in New Worktree…" to the branch-ref context menu in the graph.
- `git_gui/presentation/menus/git_menu.py` — add "Worktrees…" menu item.
- `git_gui/presentation/services/repo_change_detector.py` — extend watched-paths list to include `.git/worktrees/`.
- `git_gui/presentation/dialogs/branches.py` — render `+` badge on worktree-owning rows; route checkout through smart-switch interceptor (already happens if interceptor is on the bus side).

**Not touched:** theme tokens, QSS templates (new dialogs consume existing tokens), logger, packaging, README (until the feature ships, at which point the README is updated in the same PR per project convention).

## Domain model

```python
# git_gui/domain/entities.py
@dataclass(frozen=True)
class Worktree:
    path: Path                  # absolute filesystem path
    branch: str | None          # None when detached
    head_sha: str               # current HEAD of the worktree
    is_locked: bool
    lock_reason: str | None     # None when not locked or no reason given
    is_bare: bool
    is_main: bool               # True for the primary worktree
```

## Port additions

```python
# git_gui/domain/ports.py
class IRepositoryReader(Protocol):
    ...
    def list_worktrees(self) -> list[Worktree]: ...
    def find_worktree_for_branch(self, branch: str) -> Worktree | None: ...

class IRepositoryWriter(Protocol):
    ...
    def add_worktree(
        self,
        path: Path,
        branch: str,
        *,
        create_branch: bool,
        base_ref: str | None,
    ) -> Worktree: ...
    def remove_worktree(self, path: Path, *, force: bool) -> None: ...
    def lock_worktree(self, path: Path, *, reason: str | None) -> None: ...
    def unlock_worktree(self, path: Path) -> None: ...
```

## Infrastructure

**`pygit2/worktree_ops.py`** uses pygit2 directly for `list_worktrees`, `add_worktree`, `lookup_worktree`, `lock`, `unlock`. `find_worktree_for_branch` iterates the list and matches on the `branch` field.

**`worktree_cli.py`** wraps `git worktree remove [--force] <path>`. pygit2 has `Worktree.prune()` but not a full "remove with directory cleanup"; the subprocess path mirrors the existing `submodule_cli.py` precedent. The wrapper returns structured errors: `WorktreeDirtyError`, `WorktreeLockedError`, or generic `GitError` based on stderr parsing.

## Smart checkout

A thin interceptor on the bus's `Checkout` command handler:

```python
try:
    writer.checkout(branch)
except GitError as e:
    if _looks_like_worktree_collision(e):
        wt = reader.find_worktree_for_branch(branch)
        if wt is not None:
            switch_to_repo(wt.path)
            toast(f"Switched to worktree at {wt.path}")
            return
    raise
```

`_looks_like_worktree_collision` matches on the pygit2 error message containing `"already used by worktree"` or similar. Fragile, so the unit test covers a handful of git versions and pygit2 message variants captured from real repros.

## Dialogs

### Add Worktree

MD3 dialog (`presentation/dialogs/add_worktree.py`), follows the structure of `branches.py` and `remotes.py`:

- **Branch combo**: lists local + remote branches. Branches already in another worktree are disabled with a tooltip showing the owning path and a "Switch to that worktree" link that closes this dialog and triggers the repo switch.
- **"Create new branch" checkbox**: when toggled on, the combo is replaced by a name text field and a "Base ref" combo (defaults to the current HEAD).
- **Location field**: live-updates to `{repo_parent}/{repo_name}-{sanitized_branch}` until the user manually edits it (tracked dirty bit). Sanitize: replace `/` with `-`. Adjacent "Browse…" opens a native folder picker.
- **"Switch to new worktree after creating" checkbox** (default ON).
- Validation: path must not exist (or, if it exists, must be empty); branch name must pass `git check-ref-format`; base ref must resolve. "Add" disabled until valid.
- "Add" runs the `AddWorktree` command on a background thread, shows a busy indicator, then closes or surfaces the error inline.

### Manage Worktrees

MD3 dialog (`presentation/dialogs/worktrees.py`) modeled on `branches.py` / `remotes.py`:

- Table: Branch | Path | Locked | Status (clean / dirty / conflict).
- Row context menu / buttons: **Open**, **Lock…** (prompts for reason) / **Unlock**, **Remove…**.
- "Add Worktree…" button at the bottom opens the create dialog.

## Sidebar integration

Worktrees appear as child rows nested under the parent repo row in the multi-repo sidebar (same widget that already nests submodules). Two-line entry: line 1 = branch name or `(detached) <short sha>`; line 2 = `~`-relative path. A subtle MD3 active-row indicator marks the currently open worktree. A lock icon (MD3 outlined style) shows on locked rows with the reason in tooltip.

Click → fires the existing repo-switch signal with the worktree's path; `RepoLifecycleMixin` handles the rest.

Right-click context menu on parent repo row adds: **Add Worktree…**, **Manage Worktrees…**.
Right-click context menu on a worktree row: **Open**, **Lock…** / **Unlock**, **Remove…**.

## Branch list visual marker

Branches that own a worktree get a `+` badge after the branch name in:
- The in-repo branch sidebar tree.
- The Branches dialog (`presentation/dialogs/branches.py`).

The badge uses MD3 secondary/tertiary container colors via theme tokens. Tooltip: `Checked out at <path>`.

## Removal flow

1. User triggers Remove (context menu or Manage dialog button).
2. MD3 confirmation dialog: `Remove worktree at <path>?` → Cancel / Remove.
3. `RemoveWorktree` command runs `git worktree remove <path>` (no `--force`) on a background thread.
4. On success: row disappears from the sidebar. If the removed worktree was the active one, switch back to the parent repo.
5. On failure with stderr matching dirty / locked:
   - Second MD3 dialog explains what was found (file count for dirty, lock reason for locked).
   - Buttons: **Force remove** (destructive style — MD3 error container color) / **Cancel**.
   - On Force: re-run with `--force`.
6. Other failures: error toast + log.

## Threading

All worktree mutations run on background worker threads via the existing `_RemoteSignals`-style signal-bridge pattern. Results marshalled to the main thread. Read operations (`list_worktrees`, `find_worktree_for_branch`) are fast (directory scan) and run on the main thread inline with repo-load.

## Auto-refresh

`RepoChangeDetector` already watches `.git/`. Extend its watched-paths list to include `.git/worktrees/` (the metadata directory that mutates when worktrees are added/removed/pruned externally). The existing 200 ms debounce + full-reload pattern handles the rest — a reload re-queries `list_worktrees` and re-renders the sidebar children.

If the *active* worktree's directory vanishes externally, the existing "repo path vanished" handling (commit `958c84c`) kicks in and switches back to the parent.

## Error handling

| Failure | Surface |
|---|---|
| Path already exists / non-empty | Inline validation in Add dialog, before submit. |
| Branch already checked out elsewhere (in Add dialog) | Combo entry disabled, tooltip + "switch instead" link. |
| Worktree is dirty on remove | Second-stage force prompt with file count. |
| Worktree is locked on remove | Second-stage force prompt with lock reason. |
| Branch already checked out (smart-checkout path) | Auto-switch + toast. |
| Generic `GitError` | MD3 snackbar toast at bottom of window; full traceback in `~/.gitcrisp/logs/gitcrisp.log`. |

## Theming

All new UI strictly conforms to MD3:

- Colors exclusively via `presentation/theme/tokens.py` role tokens (`primary`, `on_surface`, `surface`, `surface_container`, `outline`, `error_container`, `secondary_container`, `tertiary`).
- Dialogs: MD3 shape (rounded corners), elevation level 3.
- Buttons: MD3 filled / outlined / text variants per emphasis level. Destructive buttons (Force remove) use `error_container` background.
- Typography: existing MD3 typography scale.
- Icons: lock icon and `+` badge use the existing MD3 icon family; no inline SVG with hard-coded fills.
- Both light and dark themes verified before merge.

## Testing

**Infrastructure** (real pygit2 repo fixtures, no mocks of git):
- `list_worktrees` shape, including main worktree, branch/path fields, lock state round-trip.
- `add_worktree` with existing branch; with `create_branch=True` + base_ref.
- `remove_worktree` clean / dirty without force (raises) / dirty with force (succeeds).
- `find_worktree_for_branch` hit / miss.
- `worktree_cli` error parsing: dirty stderr → `WorktreeDirtyError`; locked stderr → `WorktreeLockedError`; other → `GitError`.

**Application** (fake ports):
- Each command/query delegates correctly.

**Presentation** (signal-contract tests, following the pattern from commit `de33ee2`):
- Add Worktree dialog: branch combo populates; "create new" toggle flips fields; path template auto-updates until user edits; branches already in another worktree are disabled; validation gates the Add button; submit emits `AddWorktreeRequested`.
- Manage Worktrees dialog: rows render; row actions emit correct signals.
- Sidebar: worktrees nest under parent repo; click emits repo-switch signal; lock icon present on locked rows.
- Smart checkout: on the simulated "already used" error, switch signal fires with the owning path; when `find_worktree_for_branch` returns None, original error propagates.
- Remove flow: confirm → on dirty error, force prompt appears; force=True path re-issues with `--force`.
- Menus use the no-exec `QMenu` subclass from commit `faa45a3`.

**Manual verification** (before declaring done):
- Create a worktree from the Add dialog → appears in sidebar nested under parent.
- Switch into the worktree and back → working tree + branch context updates correctly.
- Externally `git worktree remove` → sidebar updates within ~2s.
- Checkout a worktree-owned branch from the Branches dialog → smart-switch toast.
- Force-remove a dirty worktree → directory is gone.
- Lock with reason, hover icon → tooltip shows reason.
- Verify both light and dark themes.

## Rollout

Single PR. Not gated behind a feature flag (consistent with how prior features like auto-change-detection and interactive rebase landed). README updated in the same PR. No data migration; existing repos with worktrees created outside GitCrisp will start appearing in the sidebar on next open.

## Out of scope (follow-ups)

These were considered and explicitly deferred:

- **Post-create hooks**: copy `.env*` files; run `uv sync` / `pnpm install`. Highest-impact differentiator surfaced by competitive research; warrants its own design.
- **Default-path templating**: user-configurable pattern (e.g., `{worktree_dir}/{branch}`) beyond the single built-in default.
- **Migrate uncommitted changes** between worktrees (VS Code's "Migrate Worktree Changes" equivalent).
- **Cross-worktree diff**: "Compare this file across worktree A and worktree B".
- **Bare-repo-as-primary** workflow: treat the worktree list as the primary view when opening a bare clone.
- **Worktree move** (`git worktree move`) — first-class in Magit, not in v1.
- **Click-to-jump** from a `+`-badged branch row directly into the owning worktree (separate from smart-checkout, which fires on checkout intent).
