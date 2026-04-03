# Staged/Unstaged Split in DiffWidget — Design Spec
_Date: 2026-04-03_

## Overview

When the "Uncommitted Changes" entry is selected in the commit graph, the `DiffWidget` currently shows a flat file list with a single diff editor. This spec adds a working-tree-specific view that splits the file list into STAGED and UNSTAGED sections, and shows both staged and unstaged diffs simultaneously when a file is selected.

---

## Architecture

`DiffWidget` manages two modes via a `QStackedWidget`:

- **Commit mode** (existing, unchanged): flat `QListView` backed by `DiffModel` + single `QPlainTextEdit`
- **Working tree mode** (new): `QTreeView` with STAGED/UNSTAGED section headers + two `QPlainTextEdit` diff editors

`load_commit(oid)` activates the correct page by checking `oid == WORKING_TREE_OID`.

---

## File List — Working Tree Mode

A `QTreeView` backed by `QStandardItemModel` with two fixed section headers:

```
STAGED
  ├── modified_file.py
  └── new_file.txt
UNSTAGED
  ├── other_file.py
  └── untracked.txt
```

- Section headers ("STAGED", "UNSTAGED") are non-selectable, non-editable `QStandardItem`s
- File items store their `FileStatus` object in `Qt.UserRole`
- Empty sections still show their header
- Tree is always fully expanded (no collapse)
- Clicking a file in either section loads both diff panels

---

## Diff Area — Working Tree Mode

A vertical `QSplitter` with two labeled sections:

```
┌──────────────────────────┐
│  Staged Changes          │  ← QLabel
│  [staged QPlainTextEdit] │
├──────────────────────────┤
│  Unstaged Changes        │  ← QLabel
│  [unstaged QPlainTextEdit│
└──────────────────────────┘
```

- Each editor is read-only, monospace, with the same coloring as the existing diff view (green `+`, red `-`, blue hunk headers)
- Editors live in a resizable `QSplitter(Vertical)`
- If a file has no staged changes the top editor is empty; if no unstaged changes the bottom is empty

---

## Infrastructure Changes

### New port method

`domain/ports.py` — `IRepositoryReader`:
```python
def get_staged_diff(self, path: str) -> list[Hunk]: ...
```

### New infrastructure implementation

`infrastructure/pygit2_repo.py` — `Pygit2Repository`:
```python
def get_staged_diff(self, path: str) -> list[Hunk]:
    # Diffs the index against HEAD tree for the given path.
    # If HEAD is unborn (no commits yet), diffs index against empty tree.
```

### New use case

`application/queries.py`:
```python
class GetStagedDiff:
    def __init__(self, reader: IRepositoryReader) -> None: ...
    def execute(self, path: str) -> list[Hunk]: ...
```

### QueryBus extension

`presentation/bus.py` — `QueryBus`:
```python
get_staged_diff: GetStagedDiff
```

`QueryBus.from_reader` instantiates `GetStagedDiff(reader)`.

---

## Unchanged

- `get_file_diff(WORKING_TREE_OID, path)` continues to return the unstaged diff (working tree vs index) — used for the bottom diff editor
- `DiffModel` and the commit-mode layout are untouched
- All 59 existing tests continue to pass

---

## Files Changed

| File | Change |
|------|--------|
| `git_gui/domain/ports.py` | Add `get_staged_diff` to `IRepositoryReader` |
| `git_gui/infrastructure/pygit2_repo.py` | Implement `get_staged_diff` |
| `git_gui/application/queries.py` | Add `GetStagedDiff` class |
| `git_gui/presentation/bus.py` | Add `get_staged_diff` field + wire in `from_reader` |
| `git_gui/presentation/widgets/diff.py` | Add working tree mode with `QStackedWidget`, `QTreeView`, two diff editors |
| `tests/infrastructure/test_reads.py` | Add `get_staged_diff` tests |
| `tests/application/test_queries.py` | Add `GetStagedDiff` test |
