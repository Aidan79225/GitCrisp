# Cherry-pick, Revert, and Reset — Design

**Date:** 2026-04-14
**Status:** Approved

## Goal

Fill three operational gaps relative to mainstream Git GUIs (Sourcetree, Fork, GitKraken, Sublime Merge): cherry-pick a commit, revert a commit, and reset the current branch to an arbitrary commit. Bundle them into a single spec because they share one entry point — the commit context menu in the graph — and one implementation pattern.

## Scope

Single-commit operations only. Multi-select is explicitly out of scope for this release. Entry points are the commit context menu in the graph; no menubar or toolbar entries in this spec.

- Cherry-pick a single commit onto HEAD.
- Revert a single commit on HEAD.
- Reset the current branch to a selected commit in soft / mixed / hard mode.

## UX Decisions

| Concern | Decision |
|---|---|
| Entry point | Commit context menu in the graph only. |
| Cherry-pick / revert UX | One-shot — no dialog. Executes immediately with Git's default commit message. |
| Reset UX | Always shows a confirmation dialog with a radio group (soft / mixed / hard), target commit summary, and, for hard, a dirty-file list. |
| Merge-commit handling | Hardcode mainline parent to `-m 1` for both cherry-pick and revert. Correct for the common case; edge cases are not addressed in v1. |
| Conflicts | Rely on the existing conflict banner. Extend banner state recognition to include `CHERRY_PICKING` and `REVERTING`. |
| Multi-select | Not supported in v1. |

## Approach

Hybrid adapter strategy, consistent with the project rule "pygit2 first, subprocess where pygit2 lacks reliable support":

- **Reset** uses `pygit2.Repository.reset(oid, reset_type)` directly.
- **Cherry-pick** and **revert** shell out to `git`, in a new `infrastructure/commit_ops_cli.py` adapter. pygit2 does not accept a mainline parameter, so reimplementing `-m 1` handling on top of `merge_commits` would duplicate code that `git` already performs correctly. The subprocess approach also writes `CHERRY_PICK_HEAD` / `REVERT_HEAD` correctly for free.

## Architecture & files touched

```
git_gui/
├── domain/
│   ├── entities.py              # + ResetMode enum
│   └── ports.py                 # + cherry_pick, revert_commit, reset_to,
│                                #   cherry_pick_abort, cherry_pick_continue,
│                                #   revert_abort, revert_continue
├── application/
│   └── commands.py              # + CherryPickCommit, RevertCommit, ResetBranch,
│                                #   CherryPickAbort, CherryPickContinue,
│                                #   RevertAbort, RevertContinue
├── infrastructure/
│   ├── commit_ops_cli.py        # NEW — subprocess adapter
│   └── pygit2_repo.py           # + reset_to; + delegation to CommitOpsCli
└── presentation/
    ├── bus.py                   # register 7 new commands
    ├── dialogs/
    │   └── reset_dialog.py      # NEW
    ├── widgets/
    │   ├── graph.py             # context-menu entries + enablement
    │   ├── working_tree.py      # banner: recognize CHERRY_PICKING / REVERTING
    │   └── diff.py              # banner: recognize CHERRY_PICKING / REVERTING
    └── main_window.py           # dispatch + reload after each command
```

## Domain additions

**`domain/entities.py`:**

```python
class ResetMode(str, Enum):
    SOFT = "SOFT"
    MIXED = "MIXED"
    HARD = "HARD"
```

`RepoState.CHERRY_PICKING` and `RepoState.REVERTING` already exist in the enum and are already mapped from pygit2's native state at `pygit2_repo.py:801`. No change needed.

**`domain/ports.py`** — seven new methods on `IRepositoryWriter`:

```python
def cherry_pick(self, oid: str) -> None: ...
def revert_commit(self, oid: str) -> None: ...
def reset_to(self, oid: str, mode: ResetMode) -> None: ...
def cherry_pick_abort(self) -> None: ...
def cherry_pick_continue(self) -> None: ...
def revert_abort(self) -> None: ...
def revert_continue(self) -> None: ...
```

No new reader methods are needed. Existing queries cover the dialog's needs: `is_dirty()`, `get_working_tree()`, `get_repo_state()`, `is_ancestor()`.

## Application layer

Seven thin use-case classes in `application/commands.py`, each following the pattern already used by `Merge`, `Rebase`, `MergeAbort`, etc. Shape:

```python
class CherryPickCommit:
    def __init__(self, writer: IRepositoryWriter):
        self._writer = writer

    def execute(self, oid: str) -> None:
        self._writer.cherry_pick(oid)
```

`ResetBranch.execute(oid: str, mode: ResetMode)` takes the mode as a second argument; all other use cases take only `oid` (or no arguments for abort/continue).

## Infrastructure

### New file — `infrastructure/commit_ops_cli.py`

Modeled on `infrastructure/submodule_cli.py`. Runs `git` in the repo's working directory, capturing stdout / stderr.

```python
class CommitOpsCli:
    def __init__(self, repo_path: str):
        self._repo_path = repo_path

    def cherry_pick(self, oid: str, is_merge: bool) -> None:
        # Git refuses `-m` on non-merge commits, so pass it only when needed.
        argv = ["git", "cherry-pick"]
        if is_merge:
            argv += ["-m", "1"]
        argv.append(oid)
        self._run(argv)

    def revert_commit(self, oid: str, is_merge: bool) -> None:
        argv = ["git", "revert", "--no-edit"]
        if is_merge:
            argv += ["-m", "1"]
        argv.append(oid)
        self._run(argv)

    def cherry_pick_abort(self) -> None:
        self._run(["git", "cherry-pick", "--abort"])

    def cherry_pick_continue(self) -> None:
        self._run(["git", "cherry-pick", "--continue"], env_overrides={"GIT_EDITOR": "true"})

    def revert_abort(self) -> None:
        self._run(["git", "revert", "--abort"])

    def revert_continue(self) -> None:
        self._run(["git", "revert", "--continue"], env_overrides={"GIT_EDITOR": "true"})

    def _run(self, argv: list[str], env_overrides: dict[str, str] | None = None) -> None:
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        result = subprocess.run(
            argv, cwd=self._repo_path, capture_output=True, text=True, env=env
        )
        if result.returncode == 0:
            return
        if self._is_conflict_exit(result):
            return
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())

    @staticmethod
    def _is_conflict_exit(result: subprocess.CompletedProcess) -> bool:
        output = (result.stderr + result.stdout).lower()
        return "conflict" in output or "after resolving the conflicts" in output
```

### `pygit2_repo.py` additions

1. Hold a `CommitOpsCli` instance alongside the existing submodule CLI:
   ```python
   self._commit_ops = CommitOpsCli(repo_path)
   ```

2. Delegate cherry-pick and revert (plus abort / continue variants) to `CommitOpsCli`. The writer methods determine `is_merge` from `len(self._repo[oid].parents) > 1` and pass it through:
   ```python
   def cherry_pick(self, oid: str) -> None:
       is_merge = len(self._repo[oid].parents) > 1
       self._commit_ops.cherry_pick(oid, is_merge)
   ```

3. Implement `reset_to` natively:
   ```python
   def reset_to(self, oid: str, mode: ResetMode) -> None:
       pygit2_type = {
           ResetMode.SOFT: pygit2.GIT_RESET_SOFT,
           ResetMode.MIXED: pygit2.GIT_RESET_MIXED,
           ResetMode.HARD: pygit2.GIT_RESET_HARD,
       }[mode]
       self._repo.reset(oid, pygit2_type)
   ```

## Presentation

### Graph context menu (`widgets/graph.py`)

Three new entries in the commit context menu, positioned in the apply / rewrite group:

```
Cherry-pick commit
Revert commit
Reset branch here ▸
  ├─ Soft  (keep index + working tree)
  ├─ Mixed (keep working tree, reset index)        [default]
  └─ Hard  (discard everything)
```

Each `Reset branch here ▸` submenu item opens `ResetDialog` pre-selected to the chosen mode. The dialog then gives the final confirmation.

**Enablement:**

- All three disabled when `repo_state != CLEAN` (reuses existing `global_disable_reason` at `graph.py:588`).
- Cherry-pick disabled when the target commit is HEAD (no-op).
- Reset submenu disabled when the selected commit is not an ancestor of the current HEAD (uses existing `is_ancestor` query).
- Everything disabled on unborn HEAD.

### New dialog — `dialogs/reset_dialog.py`

Modal, themed via existing MD3 tokens. Uses existing queries — no new domain methods.

Layout:

```
┌─ Reset <branch-name> to <short-sha> "<subject>" ─────────┐
│                                                          │
│ ○ Soft   — keep index and working tree                   │
│ ● Mixed  — keep working tree, reset index [default]      │
│ ○ Hard   — discard all uncommitted changes               │
│                                                          │
│ ⚠ The following uncommitted changes will be lost:        │  (Hard only)
│   M  src/foo.py                                          │
│   ?? src/new_file.py                                     │
│   …                                                      │
│                                                          │
│                                   [Cancel]  [Reset]      │
└──────────────────────────────────────────────────────────┘
```

- Radio group bound to `ResetMode`; default `MIXED`.
- Dirty-file list populated from `queries.get_working_tree.execute()`, shown only when `HARD` is selected. If the list is empty, show *"Working tree is clean."* in its place.
- Switching radios re-evaluates list visibility.
- `Reset` emits `accepted` with the selected mode; `Cancel` emits `rejected`.

### Banner extension

`widgets/working_tree.py::update_conflict_banner` (currently handles `MERGING`, `REBASING` at `working_tree.py:361`) gains two branches:

```python
elif state_name == "CHERRY_PICKING":
    self._banner_label.setText("\u26a0 Cherry-pick in progress")
    self._conflict_banner.setVisible(True)
elif state_name == "REVERTING":
    self._banner_label.setText("\u26a0 Revert in progress")
    self._conflict_banner.setVisible(True)
```

`widgets/diff.py::update_state_banner` at `diff.py:180`: identical two branches.

**Abort / Continue routing** — `_on_banner_abort` / `_on_banner_continue` in both widgets extended to dispatch `cherry_pick_abort` / `revert_abort` / `cherry_pick_continue` / `revert_continue` when the corresponding state is active.

### Bus wiring (`presentation/bus.py`)

Register seven new commands: `cherry_pick`, `revert_commit`, `reset_branch`, `cherry_pick_abort`, `cherry_pick_continue`, `revert_abort`, `revert_continue`.

### MainWindow orchestration

Each command dispatches synchronously from its handler, matching `_on_merge` / `_on_rebase` / `_on_merge_commit`. After completion, call `self._reload()` (the existing helper) so the banner, working-tree, and graph refresh together.

## Data flow

```
Graph context menu
    └─► MainWindow action handler
           └─► Command bus (CherryPick / Revert / Reset)
                  └─► Writer method
                         └─► CommitOpsCli (cherry-pick/revert)
                                or pygit2.Repository.reset (reset)
    └─► On completion: graph.reload_async()
           └─► queries.get_repo_state + get_commits + ...
                  └─► Banner updated (CHERRY_PICKING / REVERTING triggers banner)
                  └─► Graph repainted
```

On conflict the subprocess returns non-zero but `CommitOpsCli` swallows the exit; the reload picks up `CHERRY_PICKING` / `REVERTING` and the banner appears with Abort / Continue.

## Error handling

**Pre-flight guards (graph-level):** see Enablement above.

**Subprocess exit handling (`CommitOpsCli`):**

- Exit 0 → success.
- Non-zero with conflict markers → expected conflict pause; swallow. Caller's reload surfaces the banner.
- Non-zero for any other reason (bad SHA, corrupt repo, missing `git`) → raise `RuntimeError(stderr)`, surfaced by MainWindow via the existing status-bar error path used for merge/rebase failures.

**Specific cases:**

- Cherry-pick of a commit whose changes are already in HEAD → Git reports "empty commit". Treat as a user-visible error: *"Nothing to cherry-pick — changes are already present."* Run `git cherry-pick --abort` internally first to clear state.
- Revert of a root commit → Git refuses with a clear message; propagate.
- Reset to current HEAD → accepted as a no-op; no special case.
- Reset with dirty working tree + SOFT/MIXED → safe; dialog does not warn.
- Reset with dirty working tree + HARD → dialog shows the dirty-file list; user confirmation is the safeguard.

**Threading:** synchronous execution in the main-window handler, matching the existing merge / rebase handlers (`_on_merge`, `_on_rebase`, `_on_merge_commit`, `_on_rebase_onto_commit`). Remote operations are the only writers currently backgrounded; local-only commands like these run inline.

**Logging:** each command logs start and end via the existing `_log_panel` channel, matching merge / rebase handlers (`self._log_panel.log("Merge: ...")` on success; `self._log_panel.log_error(...)` on failure with `expand()` to surface the panel).

## Testing

Real git repositories via `tmp_path`; no mocks. Invoke all tests with `uv run pytest`.

- **`tests/infrastructure/test_commit_ops_cli.py`:**
  - `cherry_pick` clean case → HEAD has new commit with expected tree.
  - `cherry_pick` conflict → returns; `.git/CHERRY_PICK_HEAD` present.
  - `cherry_pick` invalid SHA → raises.
  - `cherry_pick` of a merge commit with `-m 1` → first parent used.
  - `revert_commit` clean → HEAD has inverse commit.
  - `revert_commit` conflict → returns; `.git/REVERT_HEAD` present.
  - `cherry_pick_abort` / `revert_abort` → state file cleared, HEAD unchanged.
  - `cherry_pick_continue` / `revert_continue` after resolution staged → commit created.

- **`tests/infrastructure/test_pygit2_repo_reset.py`:**
  - `SOFT` → HEAD moves; index + worktree unchanged.
  - `MIXED` → HEAD moves; index reset; worktree unchanged.
  - `HARD` → HEAD moves; index + worktree reset.
  - `reset_to(HEAD, HARD)` → no-op.

- **`tests/application/test_commit_ops_commands.py`:**
  - Each command delegates to the writer with expected arguments (fake writer that records calls).

- **`tests/presentation/test_reset_dialog.py`** (pytest-qt):
  - Default mode is `MIXED`.
  - Selecting `HARD` reveals the dirty-file list.
  - `HARD` with clean worktree shows "Working tree is clean."
  - `Reset` emits `accepted` with the selected mode.
  - `Cancel` emits `rejected`.

- **`tests/presentation/test_graph_context_menu.py`** (extend or new):
  - Entries disabled on non-CLEAN state.
  - Cherry-pick disabled on HEAD.
  - Reset submenu disabled when target is not an ancestor of HEAD.

- **Banner integration:** extend existing banner tests to cover `CHERRY_PICKING` / `REVERTING` labels and abort/continue routing via a fake writer.

No full end-to-end GUI test, consistent with existing project norms.

## Out of scope

- Multi-commit selection for cherry-pick or revert.
- Merge-commit mainline selection UI (hardcoded `-m 1` in v1).
- Menubar or toolbar entries.
- Cherry-pick of ranges (`A..B`).
- Reset "sideways" (to a commit that is not an ancestor of HEAD).
