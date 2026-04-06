# Working Detail: Discard & New-File Hunks Design

Date: 2026-04-06

## Overview

Three related improvements to the working detail view:

1. Newly added (untracked) files render their content as hunks instead of an empty diff panel.
2. Each hunk header on the **unstaged** side gains an X button to discard that single hunk after a confirmation dialog.
3. Right-clicking a row in the working file list shows a context menu with **Discard changes**, also gated by a confirmation dialog.

All three share new domain/application plumbing for discard operations.

---

## Feature 1: Hunks for newly added files

### Problem
`pygit2_repo.py` `get_file_diff()` (~line 157) calls `self._repo.diff()`, which does not include untracked files. New files appear in the file list but the right-hand hunk panel is empty.

### Behavior
When `get_file_diff()` is asked about a path whose status is untracked:

- **Binary detection:** read up to the first 8KB; if a NUL byte is present, treat as binary.
  - Render a single synthetic hunk: header `@@ -0,0 +1,1 @@`, one line `+Binary file`.
- **Size guard:** otherwise read the full file. If line count `> 5000` or byte size `> 1_048_576`, render a single synthetic hunk with one line `+Large file (N lines, M bytes)`.
- **Normal case:** render a single hunk with header `@@ -0,0 +1,N @@` and every line prefixed with `+`. Preserve original line endings as displayed by the existing widget.

The synthesised hunk uses the same `Hunk` dataclass the rest of the view consumes, so `HunkDiffWidget` requires no changes.

### Files touched
- `git_gui/infrastructure/pygit2_repo.py` — `get_file_diff()`

---

## Feature 2: Discard-hunk X button

### UI
- In `presentation/widgets/hunk_diff.py` (~line 120), the hunk header row currently shows a checkbox + header text. Add a `QToolButton` at the right edge of the row using `arts/ic_close.svg`.
- The button is **only visible on the unstaged instance** of `HunkDiffWidget`. Pass an `is_staged: bool` flag into the widget constructor; when `True`, do not create the button.
- The button is also hidden for untracked files (per-hunk discard of a brand-new file is meaningless; the file-level menu in Feature 3 handles that case).
- Tooltip: `Discard this hunk`.

### Interaction
1. User clicks X.
2. `QMessageBox.question` (pattern from `main_window.py:243`) with text:
   `Discard this hunk? This cannot be undone.`
   Buttons: Yes / No, default No.
3. On Yes, the widget emits a new signal `discard_hunk_requested(file_path: str, hunk: Hunk)`.
4. The signal is wired to a new `DiscardHunk` application command.

### Implementation
- The command applies the hunk in **reverse** to the working tree. Use `git apply --reverse` against a patch built from the single hunk, or the pygit2 equivalent (`Diff.parse_diff` + `apply` with `GIT_APPLY_REVERSE`). The existing `stage_hunk` / `unstage_hunk` code in the writer is the reference for how patches are constructed.
- After success, refresh the working tree model via the same refresh path used by stage/unstage today.

### Files touched
- `git_gui/presentation/widgets/hunk_diff.py`
- `git_gui/application/commands.py` — add `DiscardHunk`
- `git_gui/domain/ports.py` — add `discard_hunk(path, hunk)` to writer interface
- `git_gui/infrastructure/pygit2_repo.py` — implement `discard_hunk`
- Wherever `HunkDiffWidget` is instantiated for the staged vs unstaged panels — pass `is_staged=...`

---

## Feature 3: Right-click "Discard changes" on a file

### UI
- In `presentation/widgets/working_tree.py`, set `setContextMenuPolicy(Qt.CustomContextMenu)` and connect `customContextMenuRequested` to a handler. Pattern from `presentation/widgets/repo_list.py:142`.
- Build a `QMenu` with one action: **Discard changes**.
- On trigger, show `QMessageBox.question`:
  `Discard all changes to <filename>? This cannot be undone.`
  Buttons: Yes / No, default No.
- On Yes, dispatch a new `DiscardFile` command.

### Discard semantics (per file status)
This is the **B + C + D + E** combination from brainstorming — fully throw away all local state for the file:

| Status                                  | Action                                                  |
| --------------------------------------- | ------------------------------------------------------- |
| Modified (M)                            | `checkout HEAD -- <file>` (resets both index + workdir) |
| Deleted (D)                             | `checkout HEAD -- <file>` (restores from HEAD)          |
| Staged-add (A) — no HEAD blob           | unstage, then unlink from disk                          |
| Untracked (?)                           | unlink from disk                                        |
| Combo (e.g. staged add + further mods)  | `checkout HEAD --` if HEAD blob exists, else unstage + unlink |

The implementation can detect "HEAD has a blob for this path" via pygit2 and branch on that, rather than trying to enumerate every status combination explicitly.

### Files touched
- `git_gui/presentation/widgets/working_tree.py`
- `git_gui/application/commands.py` — add `DiscardFile`
- `git_gui/domain/ports.py` — add `discard_file(path)` to writer interface
- `git_gui/infrastructure/pygit2_repo.py` — implement `discard_file`

---

## Shared plumbing

- New writer port methods: `discard_file(path)`, `discard_hunk(path, hunk)`.
- New application commands `DiscardFile`, `DiscardHunk` mirroring the shape of existing `StageFiles` / `StageHunk`.
- Both commands trigger the same working-tree refresh that staging commands do today.

## Testing

- Unit: `pygit2_repo.get_file_diff` returns expected synthetic hunks for: text untracked file, binary untracked file (NUL byte), oversized untracked file (>5000 lines and >1MB).
- Unit: `discard_file` against each status case (M, D, A, ?, combo) — fixture repo, assert post-state.
- Unit: `discard_hunk` reverses the right hunk and leaves siblings untouched.
- Manual: X button visible only on unstaged side and hidden for untracked files; right-click menu appears on each row type; both confirmation dialogs default to No.

## Out of scope

- Discarding hunks on the **staged** side (option B/C from brainstorming) — explicitly excluded.
- Multi-select discard from the file list — single row only for now.
- Undo for discard operations.
