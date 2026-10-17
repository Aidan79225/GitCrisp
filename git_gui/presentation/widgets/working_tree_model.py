from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal

from git_gui.domain.entities import FileStatus, StagingState
from git_gui.presentation.bus import CommandBus


class WorkingTreeModel(QAbstractListModel):
    files_changed = Signal()
    # A checkbox click runs in a mouse handler, where an exception would only
    # reach the crash log; this carries the reason to the panel instead.
    operation_failed = Signal(str)

    def __init__(self, commands, parent=None) -> None:
        super().__init__(parent)
        self._commands = commands
        self._files: list[FileStatus] = []
        self._partial: set[str] = set()

    def set_commands(self, commands: CommandBus | None) -> None:
        self._commands = commands

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
            return fs.path
        if role == Qt.CheckStateRole:
            if fs.path in self._partial:
                return Qt.CheckState.PartiallyChecked
            return (
                Qt.CheckState.Checked
                if fs.status == StagingState.STAGED
                else Qt.CheckState.Unchecked
            )
        if role == Qt.UserRole:
            return fs
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if role != Qt.CheckStateRole or not index.isValid():
            return False
        fs = self._files[index.row()]
        # Toggle based on current state: Checked → unstage, anything else → stage
        unstaging = self.data(index, Qt.CheckStateRole) == Qt.CheckState.Checked
        try:
            if unstaging:
                self._commands.unstage_files.execute([fs.path])
            else:
                self._commands.stage_files.execute([fs.path])
        except Exception as e:
            verb = "Unstage" if unstaging else "Stage"
            self.operation_failed.emit(f"{verb} failed for {fs.path}: {e}")
            return False
        self.files_changed.emit()
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
