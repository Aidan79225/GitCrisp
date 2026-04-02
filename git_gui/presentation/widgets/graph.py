# git_gui/presentation/widgets/graph.py
from __future__ import annotations
from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import QTableView, QVBoxLayout, QWidget, QHeaderView
from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.graph_model import GraphModel


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
        self._view.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._view.setEditTriggers(QTableView.NoEditTriggers)

        self._model = GraphModel([], {})
        self._view.setModel(self._model)

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

        from git_gui.domain.entities import Commit
        from datetime import datetime
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
        self._view.selectionModel().currentRowChanged.connect(self._on_row_changed)

    def _on_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        oid = self._model.data(self._model.index(current.row(), 0), Qt.UserRole)
        if oid:
            self.commit_selected.emit(oid)
