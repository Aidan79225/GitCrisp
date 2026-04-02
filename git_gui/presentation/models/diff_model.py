from __future__ import annotations
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from git_gui.domain.entities import FileStatus


class DiffModel(QAbstractListModel):
    def __init__(self, files: list[FileStatus], parent=None) -> None:
        super().__init__(parent)
        self._files = files

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._files)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._files):
            return None
        f = self._files[index.row()]
        if role == Qt.DisplayRole:
            return f.path
        if role == Qt.UserRole:
            return f
        return None

    def reload(self, files: list[FileStatus]) -> None:
        self.beginResetModel()
        self._files = files
        self.endResetModel()
