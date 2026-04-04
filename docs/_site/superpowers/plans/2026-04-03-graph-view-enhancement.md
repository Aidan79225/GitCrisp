# Graph View Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add commit hash column, branch badge labels, and a real DAG graph to the commit graph panel.

**Architecture:** `GraphModel` gains a `LaneData` dataclass and a `_compute_lanes()` algorithm. Two new delegates (`GraphLaneDelegate`, `RefBadgeDelegate`) handle painting for columns 0 and 2. `GraphWidget` installs the delegates and adjusts column widths. No changes outside the presentation layer.

**Tech Stack:** Python 3.13, PySide6 6.11, pytest, pytest-qt

---

## File Map

| File | Change |
|------|--------|
| `git_gui/presentation/models/graph_model.py` | Add `LaneData`, `_compute_lanes`, update `data()` |
| `git_gui/presentation/widgets/graph.py` | Install delegates, fix column widths |
| `git_gui/presentation/widgets/graph_lane_delegate.py` | New — draws graph lanes in column 0 |
| `git_gui/presentation/widgets/ref_badge_delegate.py` | New — draws branch badges in column 2 |
| `tests/presentation/test_graph_model.py` | Update one test, add 6 new tests |

---

## Task 1: GraphModel — LaneData, lane algorithm, updated data()

**Files:**
- Modify: `git_gui/presentation/models/graph_model.py`
- Modify: `tests/presentation/test_graph_model.py`

**Context:** The current `graph_model.py` returns branch names in column 1 and nothing useful for column 0. We will:
- Change column 1 to return `commit.oid[:8]`
- Add `LaneData` returned at `Qt.UserRole + 1` from column 0
- Add branch names list returned at `Qt.UserRole + 1` from column 2
- Keep `Qt.UserRole` on any column returning `commit.oid` (the existing widget relies on this)

One existing test (`test_refs_column_shows_branch_names`) will break because column 1 no longer shows branch names — replace it with `test_hash_column_shows_short_oid`.

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/presentation/test_graph_model.py`:

```python
from datetime import datetime
from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import GraphModel, LaneData
from PySide6.QtCore import Qt


def _make_commit(oid="abc", msg="Initial commit", parents=None):
    return Commit(oid=oid, message=msg, author="Alice <a@a.com>",
                  timestamp=datetime(2026, 1, 1), parents=parents or [])


def test_row_count_matches_commits(qtbot):
    commits = [_make_commit("a"), _make_commit("b"), _make_commit("c")]
    model = GraphModel(commits, {})
    assert model.rowCount() == 3


def test_column_count(qtbot):
    model = GraphModel([], {})
    assert model.columnCount() == 5  # graph, refs, message, author, date


def test_message_column(qtbot):
    model = GraphModel([_make_commit("a", "feat: thing\n\nBody text")], {})
    idx = model.index(0, 2)
    assert model.data(idx, Qt.DisplayRole) == "feat: thing"


def test_author_column(qtbot):
    model = GraphModel([_make_commit()], {})
    idx = model.index(0, 3)
    assert model.data(idx, Qt.DisplayRole) == "Alice <a@a.com>"


def test_date_column(qtbot):
    model = GraphModel([_make_commit()], {})
    idx = model.index(0, 4)
    assert "2026-01-01" in model.data(idx, Qt.DisplayRole)


def test_user_role_returns_oid(qtbot):
    model = GraphModel([_make_commit("deadbeef")], {})
    idx = model.index(0, 0)
    assert model.data(idx, Qt.UserRole) == "deadbeef"


def test_hash_column_shows_short_oid(qtbot):
    commits = [_make_commit("abcdef1234")]
    model = GraphModel(commits, {})
    idx = model.index(0, 1)
    assert model.data(idx, Qt.DisplayRole) == "abcdef12"


def test_message_userrole_returns_branch_names(qtbot):
    commits = [_make_commit("abc")]
    refs = {"abc": ["main", "origin/main"]}
    model = GraphModel(commits, refs)
    idx = model.index(0, 2)
    names = model.data(idx, Qt.UserRole + 1)
    assert names == ["main", "origin/main"]


def test_lane_data_is_instance(qtbot):
    model = GraphModel([_make_commit("a")], {})
    idx = model.index(0, 0)
    ld = model.data(idx, Qt.UserRole + 1)
    assert isinstance(ld, LaneData)


def test_linear_history_all_lane_zero(qtbot):
    commits = [
        _make_commit("c", parents=["b"]),
        _make_commit("b", parents=["a"]),
        _make_commit("a", parents=[]),
    ]
    model = GraphModel(commits, {})
    for row in range(3):
        ld = model.data(model.index(row, 0), Qt.UserRole + 1)
        assert ld.lane == 0, f"row {row} expected lane 0, got {ld.lane}"


def test_branch_tip_opens_second_lane(qtbot):
    # b1 and b2 both point to "base" — b1 is processed first, takes lane 0.
    # When b2 is processed, lane 0 is already taken (waiting for "base"),
    # so b2 opens lane 1.
    commits = [
        _make_commit("b1", parents=["base"]),
        _make_commit("b2", parents=["base"]),
        _make_commit("base", parents=[]),
    ]
    model = GraphModel(commits, {})
    ld0 = model.data(model.index(0, 0), Qt.UserRole + 1)
    ld1 = model.data(model.index(1, 0), Qt.UserRole + 1)
    assert ld0.lane == 0
    assert ld1.lane == 1


def test_merge_commit_has_diagonal_edge(qtbot):
    # "m" merges p1 (lane 0, first parent) and p2 (lane 1, second parent).
    # edges_out for row 0 should contain (0, 1, ...) for the diagonal to p2's lane.
    commits = [
        _make_commit("m", parents=["p1", "p2"]),
        _make_commit("p1", parents=[]),
        _make_commit("p2", parents=[]),
    ]
    model = GraphModel(commits, {})
    ld = model.data(model.index(0, 0), Qt.UserRole + 1)
    from_to = [(e[0], e[1]) for e in ld.edges_out]
    assert (0, 1) in from_to


def test_invalid_index_returns_none(qtbot):
    model = GraphModel([], {})
    assert model.data(model.index(99, 0), Qt.DisplayRole) is None
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
uv run pytest tests/presentation/test_graph_model.py -v
```

Expected: `test_hash_column_shows_short_oid`, `test_message_userrole_returns_branch_names`, `test_lane_data_is_instance`, `test_linear_history_all_lane_zero`, `test_branch_tip_opens_second_lane`, `test_merge_commit_has_diagonal_edge` all FAIL. `test_refs_column_shows_branch_names` no longer exists.

- [ ] **Step 3: Replace `git_gui/presentation/models/graph_model.py`**

```python
# git_gui/presentation/models/graph_model.py
from __future__ import annotations
from dataclasses import dataclass, field
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from git_gui.domain.entities import Commit

COLUMNS = ["graph", "refs", "message", "author", "date"]

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


@dataclass
class LaneData:
    lane: int                                    # which lane the commit node sits in
    color_idx: int                               # index into LANE_COLORS for this lane
    n_lanes: int                                 # total lane count (used to size column)
    lines: list[tuple[int, int, int]] = field(default_factory=list)
    # (top_lane, bot_lane, color_idx) — pass-through lines spanning full row height
    edges_out: list[tuple[int, int, int]] = field(default_factory=list)
    # (from_lane, to_lane, color_idx) — lines from commit node center to bottom of row
    has_incoming: bool = False
    # True if this lane was already active before this commit (draw line from top to node)


def _compute_lanes(commits: list[Commit]) -> list[LaneData]:
    """Assign each commit a lane and compute drawing instructions for the graph column."""
    active: list[str | None] = []   # active[i] = OID whose line occupies lane i, or None
    colors: list[int] = []          # colors[i] = color_idx for lane i
    next_color = 0
    result: list[LaneData] = []

    for commit in commits:
        oid = commit.oid
        parents = commit.parents

        # ── 1. Find or open this commit's lane ──────────────────────────────
        if oid in active:
            my_lane = active.index(oid)
            has_incoming = True
        elif None in active:
            my_lane = active.index(None)
            active[my_lane] = oid
            has_incoming = False
        else:
            my_lane = len(active)
            active.append(oid)
            colors.append(next_color % 8)
            next_color += 1
            has_incoming = False

        color_idx = colors[my_lane]

        # ── 2. Build the new active state after this commit ─────────────────
        new_active = list(active)
        new_colors = list(colors)

        new_active[my_lane] = parents[0] if parents else None

        extra_parent_lanes: list[int] = []
        for p in parents[1:]:
            if p in new_active:
                extra_parent_lanes.append(new_active.index(p))
            elif None in new_active:
                slot = new_active.index(None)
                new_active[slot] = p
                extra_parent_lanes.append(slot)
            else:
                slot = len(new_active)
                new_active.append(p)
                new_colors.append(next_color % 8)
                next_color += 1
                extra_parent_lanes.append(slot)

        # ── 3. Pass-through lines (lanes that flow unchanged, excluding my_lane) ─
        lines: list[tuple[int, int, int]] = []
        for i in range(len(active)):
            if i == my_lane:
                continue
            old_oid = active[i]
            if old_oid is None:
                continue
            if old_oid in new_active:
                new_i = new_active.index(old_oid)
                lines.append((i, new_i, colors[i]))

        # ── 4. Outgoing edges from the commit node ──────────────────────────
        edges_out: list[tuple[int, int, int]] = []
        if parents:
            edges_out.append((my_lane, my_lane, color_idx))   # first parent straight down
        for target_lane in extra_parent_lanes:
            edges_out.append((my_lane, target_lane, color_idx))  # merge diagonals

        # ── 5. Trim trailing Nones ───────────────────────────────────────────
        while new_active and new_active[-1] is None:
            new_active.pop()
            new_colors.pop()

        n_lanes = max(len(new_active), my_lane + 1, 1)
        result.append(LaneData(
            lane=my_lane,
            color_idx=color_idx,
            n_lanes=n_lanes,
            lines=lines,
            edges_out=edges_out,
            has_incoming=has_incoming,
        ))
        active = new_active
        colors = new_colors

    return result


class GraphModel(QAbstractTableModel):
    def __init__(self, commits: list[Commit], refs: dict[str, list[str]], parent=None) -> None:
        super().__init__(parent)
        self._commits = commits
        self._refs = refs
        self._lane_data: list[LaneData] = _compute_lanes(commits)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._commits)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._commits):
            return None
        commit = self._commits[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return ""
            if col == 1:
                return commit.oid[:8]
            if col == 2:
                return commit.message.split("\n")[0]
            if col == 3:
                return commit.author
            if col == 4:
                return commit.timestamp.strftime("%Y-%m-%d %H:%M")
        if role == Qt.UserRole:
            return commit.oid
        if role == Qt.UserRole + 1:
            if col == 0:
                return self._lane_data[index.row()]
            if col == 2:
                return self._refs.get(commit.oid, [])
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section].capitalize()
        return None

    def reload(self, commits: list[Commit], refs: dict[str, list[str]]) -> None:
        self.beginResetModel()
        self._commits = commits
        self._refs = refs
        self._lane_data = _compute_lanes(commits)
        self.endResetModel()
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/presentation/test_graph_model.py -v
```

Expected: all 13 tests PASS.

- [ ] **Step 5: Run the full suite to check for regressions**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS (63 existing + 6 new - 1 removed = 68 total).

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/models/graph_model.py tests/presentation/test_graph_model.py
git commit -m "feat: add LaneData and lane layout algorithm to GraphModel"
```

---

## Task 2: GraphLaneDelegate — draw graph lanes

**Files:**
- Create: `git_gui/presentation/widgets/graph_lane_delegate.py`

**Context:** `GraphLaneDelegate` paints column 0. It reads a `LaneData` object at `Qt.UserRole + 1` and uses `QPainter` to draw pass-through lines, incoming/outgoing edges, and the commit node circle. No tests — delegates are presentation-only. Run the full suite after to confirm no regressions.

- [ ] **Step 1: Create `git_gui/presentation/widgets/graph_lane_delegate.py`**

```python
# git_gui/presentation/widgets/graph_lane_delegate.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

LANE_W = 16   # pixels per lane column
NODE_R = 4    # commit node circle radius

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


def _lx(rect_left: int, lane: int) -> int:
    """X coordinate for the center of a lane."""
    return rect_left + lane * LANE_W + LANE_W // 2


class GraphLaneDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        lane_data = index.data(Qt.UserRole + 1)
        if lane_data is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect
        left = rect.left()
        top = rect.top()
        bot = rect.bottom()
        mid = (top + bot) // 2

        # 1. Pass-through lines (full row height, diagonal if lane changes)
        for top_lane, bot_lane, ci in lane_data.lines:
            painter.setPen(QPen(QColor(LANE_COLORS[ci % len(LANE_COLORS)]), 2))
            painter.drawLine(_lx(left, top_lane), top, _lx(left, bot_lane), bot)

        # 2. Incoming line (top of cell → commit node, only if lane was active above)
        if lane_data.has_incoming:
            painter.setPen(QPen(QColor(LANE_COLORS[lane_data.color_idx % len(LANE_COLORS)]), 2))
            lx = _lx(left, lane_data.lane)
            painter.drawLine(lx, top, lx, mid)

        # 3. Outgoing edges (commit node → bottom of cell, straight or diagonal)
        for from_lane, to_lane, ci in lane_data.edges_out:
            painter.setPen(QPen(QColor(LANE_COLORS[ci % len(LANE_COLORS)]), 2))
            painter.drawLine(_lx(left, from_lane), mid, _lx(left, to_lane), bot)

        # 4. Commit node (filled circle drawn last so it sits on top of lines)
        lx = _lx(left, lane_data.lane)
        node_color = QColor(LANE_COLORS[lane_data.color_idx % len(LANE_COLORS)])
        painter.setBrush(node_color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(lx - NODE_R, mid - NODE_R, NODE_R * 2, NODE_R * 2)

        painter.restore()
```

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS (no regressions).

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/graph_lane_delegate.py
git commit -m "feat: add GraphLaneDelegate for drawing commit graph lanes"
```

---

## Task 3: RefBadgeDelegate — draw branch badges

**Files:**
- Create: `git_gui/presentation/widgets/ref_badge_delegate.py`

**Context:** `RefBadgeDelegate` paints column 2. It reads branch names at `Qt.UserRole + 1`, draws colored rounded-rect badges for each, then draws the commit message text after the badges. No tests — delegates are presentation-only.

- [ ] **Step 1: Create `git_gui/presentation/widgets/ref_badge_delegate.py`**

```python
# git_gui/presentation/widgets/ref_badge_delegate.py
from __future__ import annotations
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

BADGE_RADIUS = 4   # rounded corner radius
BADGE_H_PAD = 4    # horizontal padding inside badge
BADGE_V_PAD = 2    # vertical padding inside badge
BADGE_GAP = 4      # gap between consecutive badges, and after last badge

COLOR_HEAD = "#238636"    # green — HEAD / current branch
COLOR_REMOTE = "#1f4287"  # dark blue — remote-tracking branch (contains "/")
COLOR_LOCAL = "#0d6efd"   # blue — local branch


def _badge_color(name: str) -> QColor:
    if name == "HEAD" or name.startswith("HEAD ->"):
        return QColor(COLOR_HEAD)
    if "/" in name:
        return QColor(COLOR_REMOTE)
    return QColor(COLOR_LOCAL)


class RefBadgeDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        branch_names: list[str] = index.data(Qt.UserRole + 1) or []
        message: str = index.data(Qt.DisplayRole) or ""

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect
        x = rect.left() + 2
        cy = rect.top() + rect.height() // 2
        fm = painter.fontMetrics()
        badge_h = fm.height() + BADGE_V_PAD * 2

        for name in branch_names:
            badge_w = fm.horizontalAdvance(name) + BADGE_H_PAD * 2
            badge_rect = QRect(x, cy - badge_h // 2, badge_w, badge_h)

            painter.setBrush(QBrush(_badge_color(name)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, BADGE_RADIUS, BADGE_RADIUS)

            painter.setPen(QColor("white"))
            painter.drawText(badge_rect, Qt.AlignCenter, name)

            x += badge_w + BADGE_GAP

        # Draw commit message text after the badges
        text_rect = QRect(x, rect.top(), rect.right() - x, rect.height())
        painter.setPen(option.palette.text().color())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, message)

        painter.restore()
```

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/ref_badge_delegate.py
git commit -m "feat: add RefBadgeDelegate for drawing branch badge labels"
```

---

## Task 4: GraphWidget — install delegates and set column widths

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py`

**Context:** Wire `GraphLaneDelegate` and `RefBadgeDelegate` into the table view and set fixed column widths so everything sizes correctly. Column 2 (message) stays as `Stretch`. The existing `setSectionResizeMode(2, QHeaderView.Stretch)` line is replaced with a full column-width block.

- [ ] **Step 1: Replace `git_gui/presentation/widgets/graph.py`**

```python
# git_gui/presentation/widgets/graph.py
from __future__ import annotations
from datetime import datetime
from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import QHeaderView, QTableView, QVBoxLayout, QWidget
from git_gui.domain.entities import Commit, WORKING_TREE_OID
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.graph_model import GraphModel
from git_gui.presentation.widgets.graph_lane_delegate import GraphLaneDelegate
from git_gui.presentation.widgets.ref_badge_delegate import RefBadgeDelegate


class GraphWidget(QWidget):
    commit_selected = Signal(str)  # emits oid (or WORKING_TREE_OID)

    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries

        self._view = QTableView()
        self._view.setSelectionBehavior(QTableView.SelectRows)
        self._view.setSelectionMode(QTableView.SingleSelection)
        self._view.setShowGrid(False)
        self._view.verticalHeader().setVisible(False)
        self._view.setEditTriggers(QTableView.NoEditTriggers)

        # Column widths — column 2 (message) stretches; all others are fixed
        header = self._view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self._view.setColumnWidth(0, 120)   # graph lanes
        self._view.setColumnWidth(1, 80)    # short hash
        self._view.setColumnWidth(3, 140)   # author
        self._view.setColumnWidth(4, 130)   # date

        # Delegates
        self._view.setItemDelegateForColumn(0, GraphLaneDelegate(self._view))
        self._view.setItemDelegateForColumn(2, RefBadgeDelegate(self._view))

        self._model = GraphModel([], {})
        self._view.setModel(self._model)
        self._view.selectionModel().currentRowChanged.connect(self._on_row_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

    def reload(self) -> None:
        commits = self._queries.get_commit_graph.execute()
        branches = self._queries.get_branches.execute()
        working_tree = self._queries.get_working_tree.execute()

        refs: dict[str, list[str]] = {}
        for b in branches:
            refs.setdefault(b.target_oid, []).append(b.name)

        all_commits = list(commits)
        if working_tree:
            synthetic = Commit(
                oid=WORKING_TREE_OID,
                message="Uncommitted Changes",
                author="",
                timestamp=datetime.now(),
                parents=[commits[0].oid] if commits else [],
            )
            all_commits.insert(0, synthetic)

        self._model.reload(all_commits, refs)

    def _on_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        oid = self._model.data(self._model.index(current.row(), 0), Qt.UserRole)
        if oid:
            self.commit_selected.emit(oid)
```

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/graph.py
git commit -m "feat: install graph lane and ref badge delegates in GraphWidget"
```

---

## Self-Review

**Spec coverage:**
- ✅ Column 1 shows `oid[:8]` (Task 1, `data()`)
- ✅ Branch names returned at `Qt.UserRole + 1` from column 2 (Task 1)
- ✅ `LaneData` returned at `Qt.UserRole + 1` from column 0 (Task 1)
- ✅ Lane algorithm: linear → lane 0, branch tip → new lane, merge → diagonal edge (Task 1 algorithm + tests)
- ✅ `GraphLaneDelegate` draws pass-through lines, incoming, outgoing, node circle (Task 2)
- ✅ `RefBadgeDelegate` draws colored badges per branch name, then message text (Task 3)
- ✅ `GraphWidget` installs both delegates, fixes column widths (Task 4)

**Placeholder scan:** None found.

**Type consistency:**
- `LaneData.lines`: `list[tuple[int, int, int]]` — used as `(top_lane, bot_lane, ci)` throughout ✅
- `LaneData.edges_out`: `list[tuple[int, int, int]]` — used as `(from_lane, to_lane, ci)` throughout ✅
- `Qt.UserRole + 1` used consistently for `LaneData` (col 0) and branch names (col 2) ✅
- `_lx(rect_left, lane)` helper used consistently in delegate ✅
