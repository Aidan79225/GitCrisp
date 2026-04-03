# Commit Info Cell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 5-column graph table with a 2-column layout: graph lanes + a rich info cell showing author/date, hash/branches, and message in 3 sub-rows.

**Architecture:** `GraphModel` drops to 2 columns and gains a `CommitInfo` dataclass returned at `Qt.UserRole + 1` on column 1. A new `CommitInfoDelegate` paints the 3-sub-row layout. `GraphWidget` installs the delegate, sets row height, and hides the horizontal header.

**Tech Stack:** Python 3.13, PySide6 6.11, pytest, pytest-qt

---

## File Map

| File | Change |
|------|--------|
| `git_gui/presentation/models/graph_model.py` | Add `CommitInfo`, change `COLUMNS` to 2, update `data()` |
| `git_gui/presentation/widgets/commit_info_delegate.py` | New — paints 3-sub-row info cell |
| `git_gui/presentation/widgets/graph.py` | Install `CommitInfoDelegate`, 2-col sizing, hide header |
| `tests/presentation/test_graph_model.py` | Update 5 tests, add 2 new tests |

---

## Task 1: GraphModel — CommitInfo dataclass + 2-column data()

**Files:**
- Modify: `git_gui/presentation/models/graph_model.py`
- Modify: `tests/presentation/test_graph_model.py`

**Context:** The current model has 5 columns (`COLUMNS = ["graph", "hash", "message", "author", "date"]`). We drop to 2 (`["graph", "info"]`). Column 1 returns a `CommitInfo` dataclass at `Qt.UserRole + 1`. `Qt.UserRole` continues returning `commit.oid` for any column — the widget relies on this. Several existing tests check columns 1-4 by index and must be updated.

- [ ] **Step 1: Replace `tests/presentation/test_graph_model.py`**

```python
from datetime import datetime
from git_gui.domain.entities import Commit
from git_gui.presentation.models.graph_model import CommitInfo, GraphModel, LaneData
from PySide6.QtCore import Qt


def _make_commit(oid="abc", msg="Initial commit", parents=None):
    return Commit(oid=oid, message=msg, author="Alice <a@a.com>",
                  timestamp=datetime(2026, 1, 1, 14, 32), parents=parents or [])


def test_row_count_matches_commits(qtbot):
    commits = [_make_commit("a"), _make_commit("b"), _make_commit("c")]
    model = GraphModel(commits, {})
    assert model.rowCount() == 3


def test_column_count(qtbot):
    model = GraphModel([], {})
    assert model.columnCount() == 2  # graph, info


def test_user_role_returns_oid(qtbot):
    model = GraphModel([_make_commit("deadbeef")], {})
    idx = model.index(0, 0)
    assert model.data(idx, Qt.UserRole) == "deadbeef"


def test_commit_info_is_instance(qtbot):
    model = GraphModel([_make_commit("abc")], {})
    idx = model.index(0, 1)
    info = model.data(idx, Qt.UserRole + 1)
    assert isinstance(info, CommitInfo)


def test_commit_info_message(qtbot):
    model = GraphModel([_make_commit("a", "feat: thing\n\nBody text")], {})
    idx = model.index(0, 1)
    info = model.data(idx, Qt.UserRole + 1)
    assert info.message == "feat: thing"


def test_commit_info_author(qtbot):
    model = GraphModel([_make_commit()], {})
    idx = model.index(0, 1)
    info = model.data(idx, Qt.UserRole + 1)
    assert info.author == "Alice <a@a.com>"


def test_commit_info_timestamp(qtbot):
    model = GraphModel([_make_commit()], {})
    idx = model.index(0, 1)
    info = model.data(idx, Qt.UserRole + 1)
    assert "2026-01-01" in info.timestamp


def test_commit_info_short_oid(qtbot):
    commits = [_make_commit("abcdef1234")]
    model = GraphModel(commits, {})
    idx = model.index(0, 1)
    info = model.data(idx, Qt.UserRole + 1)
    assert info.short_oid == "abcdef12"


def test_commit_info_branch_names(qtbot):
    commits = [_make_commit("abc")]
    refs = {"abc": ["main", "origin/main"]}
    model = GraphModel(commits, refs)
    idx = model.index(0, 1)
    info = model.data(idx, Qt.UserRole + 1)
    assert info.branch_names == ["main", "origin/main"]


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


def test_badge_color_head():
    from git_gui.presentation.widgets.ref_badge_delegate import _badge_color
    color = _badge_color("HEAD")
    assert color.name().lower() == "#238636"


def test_badge_color_head_arrow():
    from git_gui.presentation.widgets.ref_badge_delegate import _badge_color
    color = _badge_color("HEAD -> main")
    assert color.name().lower() == "#238636"


def test_badge_color_remote():
    from git_gui.presentation.widgets.ref_badge_delegate import _badge_color
    color = _badge_color("origin/main")
    assert color.name().lower() == "#1f4287"


def test_badge_color_local():
    from git_gui.presentation.widgets.ref_badge_delegate import _badge_color
    color = _badge_color("main")
    assert color.name().lower() == "#0d6efd"
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
uv run pytest tests/presentation/test_graph_model.py -v
```

Expected: `test_column_count`, `test_commit_info_is_instance`, and the 5 `test_commit_info_*` tests FAIL. Lane tests pass.

- [ ] **Step 3: Replace `git_gui/presentation/models/graph_model.py`**

```python
# git_gui/presentation/models/graph_model.py
from __future__ import annotations
from dataclasses import dataclass, field
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from git_gui.domain.entities import Commit

COLUMNS = ["graph", "info"]

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


@dataclass
class CommitInfo:
    author: str
    timestamp: str       # pre-formatted "YYYY-MM-DD HH:MM"
    short_oid: str       # commit.oid[:8]
    branch_names: list[str]
    message: str         # first line of commit message only


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
            colors.append(next_color % len(LANE_COLORS))
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
                new_colors[slot] = next_color % len(LANE_COLORS)
                next_color += 1
                extra_parent_lanes.append(slot)
            else:
                slot = len(new_active)
                new_active.append(p)
                new_colors.append(next_color % len(LANE_COLORS))
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
        return len(COLUMNS)  # 2: graph, info

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._commits) or index.column() >= len(COLUMNS):
            return None
        commit = self._commits[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            return ""  # both columns fully painted by delegates
        if role == Qt.UserRole:
            return commit.oid
        if role == Qt.UserRole + 1:
            if col == 0:
                return self._lane_data[index.row()]
            if col == 1:
                return CommitInfo(
                    author=commit.author,
                    timestamp=commit.timestamp.strftime("%Y-%m-%d %H:%M"),
                    short_oid=commit.oid[:8],
                    branch_names=self._refs.get(commit.oid, []),
                    message=commit.message.split("\n")[0],
                )
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

- [ ] **Step 4: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS. Total: 73 (72 previous − 5 removed + 6 new − 0 = 73).

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/models/graph_model.py tests/presentation/test_graph_model.py
git commit -m "feat: add CommitInfo dataclass, collapse GraphModel to 2 columns"
```

---

## Task 2: CommitInfoDelegate — 3-sub-row painter

**Files:**
- Create: `git_gui/presentation/widgets/commit_info_delegate.py`

**Context:** Paints column 1. Reads `CommitInfo` from `index.data(Qt.UserRole + 1)`. Divides the cell into 3 equal sub-rows. Imports `_badge_color` from `ref_badge_delegate.py` for branch pills. No tests — presentation-only.

- [ ] **Step 1: Create `git_gui/presentation/widgets/commit_info_delegate.py`**

```python
# git_gui/presentation/widgets/commit_info_delegate.py
from __future__ import annotations
from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from git_gui.presentation.widgets.ref_badge_delegate import _badge_color

BADGE_RADIUS = 4
BADGE_H_PAD = 4
BADGE_V_PAD = 2
BADGE_GAP = 4

MUTED_COLOR = "#8b949e"   # author, datetime, hash
CELL_PAD = 4              # horizontal padding inside cell


class CommitInfoDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        fm = option.fontMetrics
        return QSize(option.rect.width(), fm.height() * 3 + 12)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        from git_gui.presentation.models.graph_model import CommitInfo
        info: CommitInfo | None = index.data(Qt.UserRole + 1)
        if info is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect
        sub_h = rect.height() // 3
        fm = painter.fontMetrics()

        # ── Sub-row 1: author (left) + datetime (right) ──────────────────────
        r1 = QRect(rect.left() + CELL_PAD, rect.top(), rect.width() - CELL_PAD * 2, sub_h)
        painter.setPen(QColor(MUTED_COLOR))
        painter.drawText(r1, Qt.AlignVCenter | Qt.AlignLeft, info.author)
        painter.drawText(r1, Qt.AlignVCenter | Qt.AlignRight, info.timestamp)

        # ── Sub-row 2: branch badges (left) + hash (right) ───────────────────
        r2_top = rect.top() + sub_h
        r2 = QRect(rect.left() + CELL_PAD, r2_top, rect.width() - CELL_PAD * 2, sub_h)
        cy2 = r2_top + sub_h // 2
        badge_h = fm.height() + BADGE_V_PAD * 2
        x = rect.left() + CELL_PAD

        for name in info.branch_names:
            badge_w = fm.horizontalAdvance(name) + BADGE_H_PAD * 2
            badge_rect = QRect(x, cy2 - badge_h // 2, badge_w, badge_h)
            painter.setBrush(QBrush(_badge_color(name)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, BADGE_RADIUS, BADGE_RADIUS)
            painter.setPen(QColor("white"))
            painter.drawText(badge_rect, Qt.AlignCenter, name)
            x += badge_w + BADGE_GAP

        # Hash right-aligned
        painter.setPen(QColor(MUTED_COLOR))
        painter.drawText(r2, Qt.AlignVCenter | Qt.AlignRight, info.short_oid)

        # ── Sub-row 3: commit message ─────────────────────────────────────────
        r3 = QRect(rect.left() + CELL_PAD, rect.top() + sub_h * 2,
                   rect.width() - CELL_PAD * 2, sub_h)
        painter.setPen(option.palette.text().color())
        painter.drawText(r3, Qt.AlignVCenter | Qt.AlignLeft, info.message)

        painter.restore()
```

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all 73 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/commit_info_delegate.py
git commit -m "feat: add CommitInfoDelegate with 3-sub-row layout"
```

---

## Task 3: GraphWidget — install delegate, 2-column sizing, hide header

**Files:**
- Modify: `git_gui/presentation/widgets/graph.py`

**Context:** Drop from 5-column to 2-column setup. Install `CommitInfoDelegate` on column 1 instead of `RefBadgeDelegate` on column 2. Hide the horizontal header. Set default row height to match `CommitInfoDelegate.sizeHint()`.

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
from git_gui.presentation.widgets.commit_info_delegate import CommitInfoDelegate


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

        # Hide column header — "Graph" / "Info" labels add no value
        self._view.horizontalHeader().setVisible(False)

        # Column widths — col 0 fixed, col 1 stretches
        header = self._view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self._view.setColumnWidth(0, 120)

        # Row height: 3 sub-rows × line height + 12px padding (4px per sub-row)
        fm = self._view.fontMetrics()
        self._view.verticalHeader().setDefaultSectionSize(fm.height() * 3 + 12)

        # Delegates
        self._view.setItemDelegateForColumn(0, GraphLaneDelegate(self._view))
        self._view.setItemDelegateForColumn(1, CommitInfoDelegate(self._view))

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
                parents=[all_commits[0].oid] if all_commits else [],
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

Expected: all 73 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add git_gui/presentation/widgets/graph.py
git commit -m "feat: wire CommitInfoDelegate, 2-column layout, hide header in GraphWidget"
```

---

## Self-Review

**Spec coverage:**
- ✅ `CommitInfo` dataclass with author, timestamp, short_oid, branch_names, message
- ✅ `COLUMNS = ["graph", "info"]` — columnCount() returns 2
- ✅ Column 0 `Qt.UserRole + 1` → `LaneData` (unchanged)
- ✅ Column 1 `Qt.UserRole + 1` → `CommitInfo`
- ✅ `Qt.UserRole` (any column) → `commit.oid` (unchanged)
- ✅ Sub-row 1: author left, datetime right, muted color
- ✅ Sub-row 2: branch badges left, hash right-aligned
- ✅ Sub-row 3: commit message, default color
- ✅ `sizeHint()` returns `fm.height() * 3 + 12`
- ✅ `GraphWidget` hides horizontal header
- ✅ `GraphWidget` sets `defaultSectionSize` to `fm.height() * 3 + 12`
- ✅ `GraphWidget` installs `CommitInfoDelegate` on col 1
- ✅ `GraphWidget` col 0 = 120px Fixed, col 1 = Stretch

**Placeholder scan:** None.

**Type consistency:** `CommitInfo` defined in Task 1, imported via `from git_gui.presentation.models.graph_model import CommitInfo` in Task 2 delegate. `_badge_color` imported from `ref_badge_delegate` in both Task 2 delegate and tests. ✅
