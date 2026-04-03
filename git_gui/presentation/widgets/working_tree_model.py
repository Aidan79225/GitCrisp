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
        self._partial: set[str] = set()

    def reload(self, files: list[FileStatus], partial: set[str] | None = None) -> None:
        self.beginResetModel()
        self._files = list(files)
        self._partial = partial or set()
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
            if fs.path in self._partial:
                return Qt.CheckState.PartiallyChecked
            return Qt.CheckState.Checked if fs.status == "staged" else Qt.CheckState.Unchecked
        if role == Qt.UserRole:
            return fs
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if role != Qt.CheckStateRole or not index.isValid():
            return False
        fs = self._files[index.row()]
        # Toggle based on current state: Checked → unstage, anything else → stage
        current = self.data(index, Qt.CheckStateRole)
        if current == Qt.CheckState.Checked:
            self._commands.unstage_files.execute([fs.path])
        else:
            self._commands.stage_files.execute([fs.path])
        self.files_changed.emit()
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
