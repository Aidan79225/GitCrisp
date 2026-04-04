# Graph View Enhancement — Design Spec
_Date: 2026-04-03_

## Overview

Three visual improvements to the commit graph panel:

1. **Hash column** — Column 1 ("refs") shows the first 8 characters of the commit OID instead of branch names.
2. **Branch badges** — Branch/tag names rendered as colored pill badges inline in the message column.
3. **Graph lanes** — Column 0 ("graph") draws the actual commit DAG topology using colored lines and circles via a custom `QPainter` delegate.

---

## Architecture

`GraphModel` gains a lane layout algorithm run in `reload()`. Two new `QStyledItemDelegate` subclasses handle painting for columns 0 and 2. `GraphWidget` installs the delegates and fixes column widths.

No changes to domain, application, infrastructure, or bus layers.

---

## Data Model — `graph_model.py`

### `LaneData` dataclass

```python
@dataclass
class LaneData:
    lane: int                         # which lane this commit's node sits in
    n_lanes: int                      # total active lanes in this row
    edges_out: list[tuple[int, int]]  # (from_lane, to_lane) lines drawn downward from this row
    color_idx: int                    # index into LANE_COLORS palette
```

Stored in a parallel list `self._lane_data: list[LaneData]` in `GraphModel`.

### Lane layout algorithm

Called at the end of `reload()`. Processes commits in order (index 0 = most recent):

```
active: list[str | None]   # active[i] = OID whose line occupies lane i
colors: list[int]          # colors[i] = color_idx for lane i (stable for lane's lifetime)
next_color: int = 0        # counter for next color to assign

For each commit c at row r:
  1. Find c's lane:
     - If c.oid in active: my_lane = active.index(c.oid)
     - Else: use first None slot in active (reuse slot, inherit slot's color), or
             append a new lane (colors.append(next_color % 8); next_color += 1)
  2. color_idx = colors[my_lane]
  3. Compute edges_out (lines leaving this row downward):
     - Each active lane i ≠ my_lane that remains active → edge (i, i) [straight]
     - First parent → edge (my_lane, my_lane) [straight, continues in same lane]
     - Each additional parent p:
       - If p already in active → edge (my_lane, active.index(p)) [merge diagonal]
       - Else → open new lane for p (assign new color), edge (my_lane, new_lane)
  4. Update active:
     - active[my_lane] = parents[0] if parents else None
     - For each additional parent: place in found/new lane
  5. Trim trailing Nones from active (and corresponding colors entries)
  6. n_lanes = len(active) (max lane index + 1, used to size column width)
  7. Store LaneData(lane=my_lane, n_lanes=n_lanes, edges_out=..., color_idx=color_idx)
```

### Updated `data()` return values

| Column | `DisplayRole` | `Qt.UserRole` |
|--------|--------------|----------------|
| 0 (graph) | `""` | `LaneData` |
| 1 (hash) | `commit.oid[:8]` | — |
| 2 (message) | first line of `commit.message` | `list[str]` branch names |
| 3 (author) | `commit.author` | — |
| 4 (date) | formatted timestamp | — |

---

## Delegates

### `graph_lane_delegate.py` — `GraphLaneDelegate(QStyledItemDelegate)`

Paints column 0. For each row:

- Reads `LaneData` from `index.data(Qt.UserRole)`.
- **Lane width:** each lane occupies `LANE_W = 16px`; total cell width = `max(n_lanes, 1) * LANE_W`.
- **Lines:** for each `(from_lane, to_lane)` in `edges_out`, draw a line from `(from_lane * LANE_W + LANE_W/2, row_center)` to `(to_lane * LANE_W + LANE_W/2, row_bottom)`. Color = `LANE_COLORS[color_idx of the source lane]`.
- **Node:** draw a filled circle at `(lane * LANE_W + LANE_W/2, row_center)`, radius 4px, color = `LANE_COLORS[color_idx]`.
- `WORKING_TREE_OID` row: draw a diamond instead of a circle.

Palette `LANE_COLORS` (8 colors, cycling):
```python
LANE_COLORS = [
    "#4fc1ff",  # blue
    "#f9c74f",  # yellow
    "#90be6d",  # green
    "#f8961e",  # orange
    "#c77dff",  # purple
    "#f94144",  # red
    "#43aa8b",  # teal
    "#adb5bd",  # grey
]
```

### `ref_badge_delegate.py` — `RefBadgeDelegate(QStyledItemDelegate)`

Paints column 2. For each row:

- Reads branch names from `index.data(Qt.UserRole)` → `list[str]`.
- For each branch name, draws a rounded-rect badge (4px radius, 3px horizontal padding, 2px vertical padding):
  - `HEAD` branch (is_head) → background `#238636` (green)
  - Remote branch (contains `/`) → background `#1f4287` (dark blue)
  - Local branch → background `#0d6efd` (blue)
- After all badges, draws the commit message text in the default style.
- Total horizontal offset for text = sum of badge widths + gaps.
- Calls `QStyledItemDelegate.initStyleOption()` then `style().drawControl()` for the text portion.

---

## Graph Widget — `graph.py`

Changes to `__init__`:

```python
from git_gui.presentation.widgets.graph_lane_delegate import GraphLaneDelegate
from git_gui.presentation.widgets.ref_badge_delegate import RefBadgeDelegate

# Column widths
self._view.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
self._view.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
self._view.setColumnWidth(0, 120)   # graph lanes
self._view.setColumnWidth(1, 80)    # short hash
self._view.setColumnWidth(3, 140)   # author
self._view.setColumnWidth(4, 130)   # date

# Delegates
self._view.setItemDelegateForColumn(0, GraphLaneDelegate(self._view))
self._view.setItemDelegateForColumn(2, RefBadgeDelegate(self._view))
```

---

## Files Changed

| File | Change |
|------|--------|
| `git_gui/presentation/models/graph_model.py` | Add `LaneData`, lane algorithm, update `data()` |
| `git_gui/presentation/widgets/graph.py` | Install delegates, set column widths |
| `git_gui/presentation/widgets/graph_lane_delegate.py` | New — paints graph column |
| `git_gui/presentation/widgets/ref_badge_delegate.py` | New — paints message column with badges |

---

## Tests

- `tests/presentation/test_graph_model.py` — add tests for lane layout:
  - Linear history assigns all commits to lane 0
  - Branch tip opens a new lane
  - Merge commit produces a diagonal edge
  - `data(col=1)` returns 8-char hash
  - `data(col=2, Qt.UserRole)` returns branch names list
  - `data(col=0, Qt.UserRole)` returns `LaneData`
- Delegates are presentation-only; not unit tested.
- All 63 existing tests continue to pass.
