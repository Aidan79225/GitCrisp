# git_gui/presentation/widgets/working_tree_model.py
from __future__ import annotations
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal
from git_gui.domain.entities import FileStatus


class WorkingTreeModel(QAbstractListModel):
    files_changed = Signal()

    def __init__(self, commands, parent=None) -> None:
        super().__init__(parent)
        self._commands = commands
        self._files: list[FileStatus] = []

    def reload(self, files: list[FileStatus]) -> None:
        self.beginResetModel()
        self._files = list(files)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._files)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._files):
            return None
        fs = self._files[index.row()]
        if role == Qt.DisplayRole:
            return f"{fs.path}  ({fs.delta})"
        if role == Qt.CheckStateRole:
            return Qt.Checked if fs.status == "staged" else Qt.Unchecked
        if role == Qt.UserRole:
            return fs
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if role != Qt.CheckStateRole or not index.isValid():
            return False
        fs = self._files[index.row()]
        if value == Qt.Checked:
            self._commands.stage_files.execute([fs.path])
        else:
            self._commands.unstage_files.execute([fs.path])
        self.files_changed.emit()
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
