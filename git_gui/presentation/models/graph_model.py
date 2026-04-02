from __future__ import annotations
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from git_gui.domain.entities import Commit

COLUMNS = ["graph", "refs", "message", "author", "date"]


class GraphModel(QAbstractTableModel):
    def __init__(self, commits: list[Commit], refs: dict[str, list[str]], parent=None) -> None:
        super().__init__(parent)
        self._commits = commits
        self._refs = refs  # {oid: ["branch", "tag", ...]}

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
                return ""  # graph lanes — painted by delegate in future
            if col == 1:
                return "  ".join(self._refs.get(commit.oid, []))
            if col == 2:
                return commit.message.split("\n")[0]
            if col == 3:
                return commit.author
            if col == 4:
                return commit.timestamp.strftime("%Y-%m-%d %H:%M")
        if role == Qt.UserRole:
            return commit.oid
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section].capitalize()
        return None

    def reload(self, commits: list[Commit], refs: dict[str, list[str]]) -> None:
        self.beginResetModel()
        self._commits = commits
        self._refs = refs
        self.endResetModel()
