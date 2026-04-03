# Commit Detail Header — Design Spec
_Date: 2026-04-04_

## Overview

Add two rows above the existing file list and diff view in the commit content area. Row 1 shows commit metadata (author, datetime, hash, parent hashes, branch/remote/tag). Row 2 shows the full commit message.

---

## Layout

```
┌──────────────────────────────────────────────────┐
│ Row 1: Commit Detail (3 lines)                   │
│   Author: Alice <alice@example.com>  2026-04-04  │
│   Commit: abcdef1234567890  [main] [origin/main] │
│   Parent: 1234567890abcdef                       │
├──────────────────────────────────────────────────┤
│ Row 2: Commit Message (full, read-only)          │
│   feat: add something useful                     │
│                                                  │
│   This is the body of the commit message.        │
├──────────────────────────────────────────────────┤
│ Row 3: File list (existing, with delta badges)   │
├──────────────────────────────────────────────────┤
│ Row 4: Diff view (existing, with line numbers)   │
└──────────────────────────────────────────────────┘
```

All four rows in a `QSplitter(Qt.Vertical)`. Row 1 and Row 2 have fixed sizes (not user-resizable). Row 3 and Row 4 stretch.

---

## Row 1: Commit Detail — `QLabel`

3 lines of text:

- **Line 1:** `Author: Alice <alice@example.com>    2026-04-04 14:32`
  - "Author:" label in muted gray (`#8b949e`), value in white, datetime right-aligned in muted gray
- **Line 2:** `Commit: abcdef1234567890abcdef1234567890abcdef12  [main] [origin/main]`
  - "Commit:" label in muted, full hash in white, branch/tag as colored pill badges (same `_badge_color` from `ref_badge_delegate.py`)
- **Line 3:** `Parent: 1234567890abcdef1234567890abcdef12345678`
  - "Parent:" label in muted, hash(es) in white. Multiple parents separated by space.

Implementation: Use a custom-painted `QWidget` (not a plain `QLabel`) so we can render colored pill badges inline on line 2. Reuse `_badge_color` from `ref_badge_delegate.py`.

Fixed height: `fm.height() * 3 + 16` (3 lines + padding).

---

## Row 2: Commit Message — `QPlainTextEdit`

- Read-only, monospace font
- No scrollbar — auto-sized to content height via `setFixedHeight`
- Shows the full commit message (all lines, not just first line)
- White text on default background

---

## Data Flow

`DiffWidget.load_commit(oid)` currently only fetches files. It now also needs:
1. The `Commit` object (author, timestamp, oid, parents, message)
2. Branch/tag refs for this commit

### New domain port

Add to `IRepositoryReader`:
```python
def get_commit(self, oid: str) -> Commit: ...
```

### New infrastructure method

Add to `Pygit2Repository`:
```python
def get_commit(self, oid: str) -> Commit:
    return _commit_to_entity(self._repo.get(oid))
```

### New query

```python
class GetCommitDetail:
    def execute(self, oid: str) -> Commit: ...
```

### Bus

Add `get_commit_detail: GetCommitDetail` to `QueryBus`.

### DiffWidget changes

`load_commit(oid)` fetches the `Commit` via `get_commit_detail`, fetches branches via `get_branches`, filters refs for this oid, and updates Row 1 and Row 2.

---

## Files Changed

| File | Change |
|------|--------|
| `git_gui/domain/ports.py` | Add `get_commit(oid) -> Commit` to `IRepositoryReader` |
| `git_gui/infrastructure/pygit2_repo.py` | Implement `get_commit(oid)` |
| `git_gui/application/queries.py` | Add `GetCommitDetail` |
| `git_gui/presentation/bus.py` | Wire `get_commit_detail` on `QueryBus` |
| `git_gui/presentation/widgets/diff.py` | Add detail widget (Row 1) + message widget (Row 2) above existing splitter |
