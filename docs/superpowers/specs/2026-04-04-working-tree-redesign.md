# Working Tree Redesign — Design Spec
_Date: 2026-04-04_

## Overview

Replace the current working tree page (staged/unstaged split with tree view) with a 3-row layout: commit toolbar, file list with per-file checkboxes, and hunk diff with per-hunk checkboxes. Extract it into a standalone `WorkingTreeWidget`, keeping `DiffWidget` for commit-mode only.

---

## Layout

```
┌─────────────────────────────────────────────────────────┐
│ Row 1: [  commit message (PlainTextEdit)  ] [Stage All] │
│                                             [Unstg All] │
│                                             [ Commit  ] │
├─────────────────────────────────────────────────────────┤
│ Row 2: File list                                        │
│  ☑ src/foo.py  (modified)                  ← selected   │
│  ☐ src/bar.py  (added)                                  │
│  ☑ README.md   (deleted)                                │
├─────────────────────────────────────────────────────────┤
│ Row 3: Diff for selected file                           │
│  ☑ @@ -10,6 +10,8 @@ def foo():                        │
│     context line                                        │
│  +  added line                          (green bg)      │
│  -  removed line                        (red bg)        │
│                                                         │
│  ☐ @@ -30,4 +32,5 @@ def bar():                        │
│     context line                                        │
│  +  added line                                          │
└─────────────────────────────────────────────────────────┘
```

- Row 1, 2, 3 in a `QSplitter(Qt.Vertical)` — resizable
- Row 1: `QPlainTextEdit` on the left, 3 `QPushButton` stacked in `QVBoxLayout` on the right
- Row 2: `QListView` with `WorkingTreeModel`
- Row 3: `HunkDiffWidget` (custom `QScrollArea`)

---

## Domain & Infrastructure

### New port methods — `IRepositoryWriter`

```python
def stage_hunk(self, path: str, hunk_header: str) -> None: ...
def unstage_hunk(self, path: str, hunk_header: str) -> None: ...
```

### Implementation — `Pygit2Repository`

pygit2 has no native hunk-apply API. Implementation:
1. Generate the full diff for the file (unstaged or staged depending on direction)
2. Find the matching hunk by its header string
3. Build a minimal patch string (diff header + single hunk)
4. Apply via `subprocess.run(["git", "apply", "--cached"], input=patch, cwd=repo_path)` for staging
5. For unstaging: `git apply --cached --reverse`

The hunk header (`@@ -10,6 +10,8 @@ def foo():`) is unique within a file's diff and serves as the hunk identifier.

### New commands — `commands.py`

```python
@dataclass
class StageHunk:
    repo: IRepositoryWriter
    def execute(self, path: str, hunk_header: str) -> None:
        self.repo.stage_hunk(path, hunk_header)

@dataclass
class UnstageHunk:
    repo: IRepositoryWriter
    def execute(self, path: str, hunk_header: str) -> None:
        self.repo.unstage_hunk(path, hunk_header)
```

### CommandBus additions

```python
stage_hunk: StageHunk
unstage_hunk: UnstageHunk
```

Existing `stage_files` and `unstage_files` remain unchanged — used for file-level checkbox, Stage All, and Unstage All.

---

## Presentation

### `WorkingTreeWidget` — `working_tree.py`

Standalone widget replacing the old working tree page in `DiffWidget`.

**Row 1 — Commit toolbar:**
- `QPlainTextEdit`: commit message input, max height ~3 lines, placeholder "Commit message..."
- 3 buttons in `QVBoxLayout`:
  - **Stage All**: `commands.stage_files([f.path for f in all_files])`
  - **Unstage All**: `commands.unstage_files([f.path for f in all_files])`
  - **Commit**: `commands.create_commit(message_text)`, clear message, reload
- Layout: `QHBoxLayout` containing the text edit (stretch) and button column (fixed)

**Row 2 — File list:**
- `QListView` with `WorkingTreeModel`
- Single selection, click selects file (highlight), triggers Row 3 diff load
- No edit triggers

**Row 3 — Hunk diff:**
- `HunkDiffWidget` instance
- Updated when a file is selected in Row 2

**Reload flow:**
- `reload()` fetches `queries.get_working_tree.execute()`
- Passes file list to `WorkingTreeModel`
- Clears Row 3

**Signals:**
- `reload_requested = Signal()` — emitted after commit or stage/unstage so MainWindow can refresh graph

### `WorkingTreeModel` — `working_tree_model.py`

Extends `QAbstractListModel`. Flat list of `FileStatus` items.

**Columns:** single column

**Roles:**
- `DisplayRole`: `"{path}  ({delta})"` — e.g. `"src/foo.py  (modified)"`
- `CheckStateRole`: `Qt.Checked` if `status == "staged"`, else `Qt.Unchecked`
- `UserRole`: the `FileStatus` object

**Flags:** `Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable`

**`setData()` for `CheckStateRole`:**
- If toggling to checked → call `commands.stage_files([path])`
- If toggling to unchecked → call `commands.unstage_files([path])`
- Emit `files_changed` signal so the widget can reload from git
- Return `True`

Constructor takes `commands: CommandBus` for stage/unstage calls.

### `HunkDiffWidget` — `hunk_diff.py`

Custom widget using `QScrollArea` containing a `QVBoxLayout` of hunk blocks.

**Each hunk block:**
- Header row: `QCheckBox` with hunk header text (e.g. `@@ -10,6 +10,8 @@ def foo():`)
  - Checked = this hunk is staged
  - Toggle calls `commands.stage_hunk(path, header)` or `commands.unstage_hunk(path, header)`
  - After toggle, re-fetches and re-renders (hunk boundaries may shift)
- Body: `QPlainTextEdit` (read-only, monospace) rendered with same diff formatting as commit diff
  - White text, green background for `+`, red background for `-`, blue for hunk headers

**`load_file(path: str)`:**
1. Fetch staged hunks: `queries.get_staged_diff.execute(path)`
2. Fetch unstaged hunks: `queries.get_file_diff.execute(WORKING_TREE_OID, path)`
3. Render all hunks: staged hunks with checkbox checked, unstaged hunks with checkbox unchecked

**Diff rendering:** Reuse the same `QTextCharFormat` / `QTextBlockFormat` pattern from `DiffWidget._render_diff()`.

### `DiffWidget` — `diff.py` (modified)

Remove all working tree code (stack page 1, `_wt_tree`, `_wt_model`, staged/unstaged diff views, `_load_working_tree`, `_on_wt_file_selected`). Keep only commit mode. Remove `QStackedWidget` — the widget is now always in commit mode.

`load_commit(oid)` no longer checks for `WORKING_TREE_OID`.

### `MainWindow` — `main_window.py` (modified)

Add `QStackedWidget` to switch between:
- Page 0: `DiffWidget` (commit mode)
- Page 1: `WorkingTreeWidget` (working tree mode)

The `graph.commit_selected` signal handler:
- If `oid == WORKING_TREE_OID` → show page 1, call `working_tree.reload()`
- Else → show page 0, call `diff.load_commit(oid)`

Wire `working_tree.reload_requested` → `self._reload()` to refresh graph after commits.

---

## Files Changed

| File | Change |
|------|--------|
| `git_gui/domain/ports.py` | Add `stage_hunk`, `unstage_hunk` to `IRepositoryWriter` |
| `git_gui/infrastructure/pygit2_repo.py` | Implement `stage_hunk`, `unstage_hunk` via `git apply --cached` |
| `git_gui/application/commands.py` | Add `StageHunk`, `UnstageHunk` |
| `git_gui/presentation/bus.py` | Wire `stage_hunk`, `unstage_hunk` on `CommandBus` |
| `git_gui/presentation/widgets/working_tree.py` | New — 3-row working tree widget |
| `git_gui/presentation/widgets/hunk_diff.py` | New — scrollable hunk diff with per-hunk checkboxes |
| `git_gui/presentation/widgets/working_tree_model.py` | New — file list model with checkboxes |
| `git_gui/presentation/widgets/diff.py` | Remove working tree code, commit mode only |
| `git_gui/presentation/main_window.py` | Add stack switching DiffWidget/WorkingTreeWidget |
| `tests/infrastructure/test_hunk_staging.py` | New — tests for stage_hunk/unstage_hunk |
| `tests/presentation/test_working_tree_model.py` | New — tests for WorkingTreeModel |
