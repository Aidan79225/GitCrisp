# Commit Info Cell — Design Spec
_Date: 2026-04-03_

## Overview

Replace the 5-column graph table (graph, hash, message, author, date) with a 2-column layout:
- **Column 0:** Graph lanes (unchanged)
- **Column 1:** A rich "info" cell painted by `CommitInfoDelegate`, displaying 3 visual sub-rows per commit

---

## Architecture

`GraphModel` drops to 2 columns. A new `CommitInfo` dataclass carries all data column 1 needs. A new `CommitInfoDelegate` paints column 1 with 3 equal sub-rows. `GraphWidget` installs the delegate, adjusts column/row sizing, and hides the horizontal header.

No changes to domain, application, infrastructure, or bus layers.

---

## Data Model — `graph_model.py`

### `CommitInfo` dataclass

```python
@dataclass
class CommitInfo:
    author: str
    timestamp: str       # pre-formatted: "2026-01-01 14:32"
    short_oid: str       # commit.oid[:8]
    branch_names: list[str]
    message: str         # first line of commit message only
```

### Column structure

```python
COLUMNS = ["graph", "info"]  # columnCount() returns 2
```

### `data()` return values

| Column | `DisplayRole` | `Qt.UserRole` | `Qt.UserRole + 1` |
|--------|--------------|----------------|-------------------|
| 0 (graph) | `""` | `commit.oid` | `LaneData` |
| 1 (info)  | `""` | `commit.oid` | `CommitInfo` |

`Qt.UserRole` continues to return `commit.oid` for any column — the widget selection logic relies on this.

---

## `CommitInfoDelegate` — `commit_info_delegate.py`

Paints column 1. Reads `CommitInfo` from `index.data(Qt.UserRole + 1)`.

### Visual layout (3 equal sub-rows)

```
┌─────────────────────────────────────────────────┐
│ Alice <a@a.com>              2026-01-01 14:32   │  sub-row 1
│ [main] [origin/main]                  abcdef12 │  sub-row 2
│ feat: add something useful                      │  sub-row 3
└─────────────────────────────────────────────────┘
```

- **Sub-row 1:** author left-aligned, datetime right-aligned. Muted color (`#8b949e`).
- **Sub-row 2:** branch badge pills left-aligned (using `_badge_color` from `ref_badge_delegate.py`), short hash right-aligned. Hash in muted monospace color.
- **Sub-row 3:** commit message left-aligned. Default palette text color.

All sub-rows have equal height: `sub_h = rect.height() // 3`.

### `sizeHint()`

```python
def sizeHint(self, option, index):
    fm = option.fontMetrics
    return QSize(option.rect.width(), fm.height() * 3 + 12)
```

### Badge rendering

Reuses `_badge_color(name)` imported from `ref_badge_delegate.py`. Same rounded-rect pill style (4px radius, 4px h-pad, 2px v-pad, white text).

---

## GraphWidget — `graph.py`

Changes to `__init__`:

- Remove `RefBadgeDelegate` installation (column 2 no longer exists)
- Install `CommitInfoDelegate` on column 1
- Column widths: col 0 = 120px Fixed, col 1 = Stretch (only 2 columns now)
- Hide horizontal header: `self._view.horizontalHeader().setVisible(False)`
- Set default row height to match delegate: `self._view.verticalHeader().setDefaultSectionSize(fm.height() * 3 + 12)`

Where `fm` is obtained from `self._view.fontMetrics()`.

---

## Tests — `tests/presentation/test_graph_model.py`

Tests to update (they reference columns that no longer exist):
- `test_column_count` → assert `== 2`
- `test_message_column` → read from `CommitInfo.message` via `Qt.UserRole + 1` on col 1
- `test_author_column` → read from `CommitInfo.author` via `Qt.UserRole + 1` on col 1
- `test_date_column` → read from `CommitInfo.timestamp` via `Qt.UserRole + 1` on col 1
- `test_hash_column_shows_short_oid` → read from `CommitInfo.short_oid` via `Qt.UserRole + 1` on col 1
- `test_message_userrole_returns_branch_names` → read from `CommitInfo.branch_names` via `Qt.UserRole + 1` on col 1

New tests to add:
- `test_commit_info_is_instance` — `Qt.UserRole + 1` on col 1 returns `CommitInfo`
- `test_commit_info_fields` — all fields populated correctly for a known commit

---

## Files Changed

| File | Change |
|------|--------|
| `git_gui/presentation/models/graph_model.py` | Add `CommitInfo`, change to 2 columns, update `data()` |
| `git_gui/presentation/widgets/commit_info_delegate.py` | New — 3-sub-row painter |
| `git_gui/presentation/widgets/graph.py` | Install delegate, 2-column sizing, hide header |
| `tests/presentation/test_graph_model.py` | Update column tests, add CommitInfo tests |
