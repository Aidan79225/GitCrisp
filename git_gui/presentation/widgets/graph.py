# git_gui/presentation/widgets/graph.py
from __future__ import annotations
from datetime import datetime
from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import QHeaderView, QTableView, QVBoxLayout, QWidget
from git_gui.domain.entities import Commit, WORKING_TREE_OID
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.graph_model import GraphModel
from git_gui.presentation.widgets.graph_lane_delegate import GraphLaneDelegate, LANE_W
from git_gui.presentation.widgets.commit_info_delegate import (
    CommitInfoDelegate, BADGE_GAP, BADGE_H_PAD, CELL_PAD,
)


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

        # Row height: 2 header rows + up to 3 message lines + padding
        fm = self._view.fontMetrics()
        self._view.verticalHeader().setDefaultSectionSize(fm.height() * 5 + 24)

        # Delegates
        self._view.setItemDelegateForColumn(0, GraphLaneDelegate(self._view))
        self._view.setItemDelegateForColumn(1, CommitInfoDelegate(self._view))

        self._model = GraphModel([], {})
        self._view.setModel(self._model)

        # Column widths — col 0 fixed, col 1 stretches with splitter
        header = self._view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self._view.setColumnWidth(0, LANE_W)
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

        # Auto-fit graph column width to the max lane count
        max_lanes = max(
            (self._model.data(self._model.index(r, 0), Qt.UserRole + 1).n_lanes
             for r in range(self._model.rowCount())),
            default=1,
        )
        self._view.setColumnWidth(0, max_lanes * LANE_W + LANE_W)

        # Auto-fit info column minimum width to content
        fm = self._view.fontMetrics()
        gap = CELL_PAD * 2
        spacing = fm.horizontalAdvance("  ")  # space between left/right items
        min_info_w = 0
        for r in range(self._model.rowCount()):
            info = self._model.data(self._model.index(r, 1), Qt.UserRole + 1)
            if info is None:
                continue
            author = info.author.split("<")[0].strip() if "<" in info.author else info.author
            # Row 1: author + timestamp
            w1 = fm.horizontalAdvance(author) + fm.horizontalAdvance(info.timestamp) + spacing
            # Row 2: badges + hash
            badges_w = sum(
                fm.horizontalAdvance(n) + BADGE_H_PAD * 2 + BADGE_GAP
                for n in info.branch_names
            )
            w2 = badges_w + fm.horizontalAdvance(info.short_oid) + spacing
            min_info_w = max(min_info_w, w1, w2)

        min_info_w += gap
        graph_w = max_lanes * LANE_W + LANE_W
        self._view.setMinimumWidth(graph_w + min_info_w)

    def _on_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        oid = self._model.data(self._model.index(current.row(), 0), Qt.UserRole)
        if oid:
            self.commit_selected.emit(oid)
