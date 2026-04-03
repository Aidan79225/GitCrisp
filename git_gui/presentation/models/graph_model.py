# git_gui/presentation/models/graph_model.py
from __future__ import annotations
from dataclasses import dataclass, field
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from git_gui.domain.entities import Commit

COLUMNS = ["graph", "hash", "message", "author", "date"]

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
        return len(COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._commits) or index.column() >= len(COLUMNS):
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
