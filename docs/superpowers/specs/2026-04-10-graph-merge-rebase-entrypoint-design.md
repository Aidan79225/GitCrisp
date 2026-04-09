# Commit Graph Merge/Rebase Entry Point — Design

**Status:** Draft
**Date:** 2026-04-10
**Scope:** Spec A of three (A: graph entry point, B: merge options UI, C: conflict resolution flow)

## Background

Today, merge and rebase can only be triggered by right-clicking a branch in the sidebar (`main_window.py:113-114`, `commands.py:102-115`). The commit graph context menu (`graph.py:393-451`) supports Create Branch / Create Tag / Checkout / Delete branch but has no merge/rebase entry. There is also no detection of in-progress repository states (MERGING, REBASING, etc.), so users can repeatedly trigger operations that will fail.

This spec adds merge/rebase entries to the commit graph context menu, with state-aware enabling.

Out of scope (deferred to later specs):
- Merge options (ff-only / no-ff / squash / commit message editing) — Spec B
- Conflict resolution UI, `--continue` / `--abort` — Spec C
- Toolbar or menu-bar entry points — not planned

## Goals

- Let users initiate merge and rebase from the commit graph against any commit, not only branches.
- Make menu labels unambiguous about source and target ("Merge feature into main").
- Prevent obviously broken invocations (detached HEAD, repo mid-merge, no-op merges) by disabling with explanatory tooltips.
- Reuse existing command infrastructure; do not introduce new error-handling patterns.

## Behavior

### Targets shown

When the user right-clicks commit `X` (HEAD is on branch `H`, `X` carries branches `B1, B2, ...`):

For each branch `B` on `X` where `B != H`:
- `Merge {B} into {H}`
- `Rebase {H} onto {B}`

Plus, generic commit-targeted actions:
- `Merge commit {short_oid} into {H}` — shown when `X != HEAD` and `X` is not an ancestor of HEAD
- `Rebase {H} onto commit {short_oid}` — shown when `X != HEAD`

`{short_oid}` is the 7-character abbreviation already used elsewhere in the UI.

### Disabled (shown but greyed out, with tooltip)

- **HEAD is detached** — every merge/rebase action disabled. Tooltip: `HEAD is detached — checkout a branch first`.
- **Repository state is MERGING / REBASING / CHERRY_PICKING / REVERTING** — every action disabled. Tooltip: `Repository is in {STATE} — resolve or abort first`.
- **`X` is an ancestor of HEAD and `X` carries branch `B`** — `Merge {B} into {H}` disabled with tooltip `Already up to date`. (The corresponding rebase is still allowed; rebasing onto an ancestor is a valid no-op operation a user might still want.)

`menu.setToolTipsVisible(True)` is required so QMenu actually renders the tooltips.

### Hidden (not shown at all)

- The entire merge/rebase section is omitted when there are zero candidate actions — e.g., right-clicking HEAD itself when no other branch sits on that commit.

### Placement

A new section appears in `_show_context_menu` after the existing "Delete branch" block, separated by `addSeparator()`. Order within the section: branch-targeted merges, branch-targeted rebases, then generic commit-targeted merge, then generic commit-targeted rebase. Multiple branches produce multiple top-level actions (no submenu) to keep labels visible — the existing Checkout submenu pattern is for cases where the action label would otherwise repeat, which is not an issue here because each label embeds the branch name.

## Architecture

### Domain (`domain/ports.py`)

`RepoReader` gains:
- `repo_state() -> RepoStateInfo` — returns enum + current branch name (None if detached)
- `is_ancestor(ancestor_oid: str, descendant_oid: str) -> bool`

`RepoWriter` gains:
- `merge_commit(oid: str) -> None`
- `rebase_onto_commit(oid: str) -> None`

New dataclass `RepoStateInfo(state: RepoState, head_branch: str | None)` and enum `RepoState` (`CLEAN`, `MERGING`, `REBASING`, `CHERRY_PICKING`, `REVERTING`, `DETACHED_HEAD`) live in `domain/` alongside existing types.

### Infrastructure (`infrastructure/pygit2_repo.py`)

- `repo_state()` — maps `repo.state()` to the enum; collapses detached-HEAD via `repo.head_is_detached`. Reports `head_branch` from `repo.head.shorthand` when not detached.
- `is_ancestor(a, d)` — wraps `repo.descendant_of(d, a)`.
- `merge_commit(oid)` / `rebase_onto_commit(oid)` — share an internal helper with existing `merge` / `rebase`. The branch-name variants resolve a name to an oid then call the shared core, so behavior remains identical for sidebar usage.

### Application

- `application/queries.py`: new `GetRepoState` query wrapping `RepoReader.repo_state()`.
- `application/commands.py`: new `MergeCommit` and `RebaseOntoCommit`, mirroring `Merge` and `Rebase` but taking an oid.

### Presentation

`presentation/widgets/graph.py`:
- 4 new signals: `merge_branch_requested(str)`, `merge_commit_requested(str)`, `rebase_onto_branch_requested(str)`, `rebase_onto_commit_requested(str)`.
- `_show_context_menu` calls `self._queries.get_repo_state.execute()` once and computes ancestor relationships via `self._queries` / reader.
- New helper builds the merge/rebase section using the rules above. Disabled actions get `setEnabled(False)` and `setToolTip(...)`.
- `QMenu` is constructed with `setToolTipsVisible(True)`.

`presentation/main_window.py`:
- Wires the 4 new signals.
- New handlers `_on_merge_commit` / `_on_rebase_onto_commit` follow the existing try/except → `log_panel` pattern (`main_window.py:204-219`). Branch-targeted signals reuse the existing `_on_merge` / `_on_rebase`.

### Error handling

Identical to today: pygit2 exceptions surface to the handler, which logs an error line. With state detection in place, the most common "I'm in a merge state already" failures are now prevented at the menu level rather than reported after the fact.

## Testing

### Unit

- `tests/application/test_commands.py` — `MergeCommit`, `RebaseOntoCommit`: confirm correct oid passed to a mock writer.
- `tests/application/test_queries.py` — `GetRepoState`: mock reader returning each enum value, confirm passthrough.
- `tests/infrastructure/test_pygit2_repo.py` (or matching file) — temp-repo integration tests for `repo_state()` (clean, merging, rebasing, detached), `is_ancestor()`, `merge_commit()`, `rebase_onto_commit()`.

### Widget

`tests/presentation/test_graph.py` (create if absent), using `pytest-qt` and fake queries/commands. Cases:

- HEAD detached → all merge/rebase actions disabled with the detached tooltip.
- Repo state MERGING → all disabled with the state tooltip.
- Right-click on HEAD with no other branches → entire section hidden.
- Right-click on a commit that is ancestor of HEAD and carries branch `B` → `Merge B into H` disabled with `Already up to date`; `Rebase H onto B` still enabled.
- Multiple branches on one commit → one merge action and one rebase action per branch, all enabled.
- Normal commit not on HEAD → `Merge commit … into H` and `Rebase H onto commit …` both present and emit the right oid.

### Manual acceptance

- Right-click various commits in a clean repo and confirm menu contents match the rules.
- Trigger a merge conflict, then right-click any commit — confirm everything in the section is disabled with the MERGING tooltip.
- Detach HEAD (`Checkout (detached HEAD)`), right-click — confirm everything disabled with the detached tooltip.

## File change list

Modified:
- `git_gui/domain/ports.py`
- `git_gui/infrastructure/pygit2_repo.py`
- `git_gui/application/queries.py`
- `git_gui/application/commands.py`
- `git_gui/presentation/widgets/graph.py`
- `git_gui/presentation/main_window.py`

Test files added or modified:
- `tests/application/test_commands.py`
- `tests/application/test_queries.py`
- `tests/infrastructure/test_pygit2_repo.py`
- `tests/presentation/test_graph.py`

No new production files.
