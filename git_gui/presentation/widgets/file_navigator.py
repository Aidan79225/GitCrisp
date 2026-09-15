"""FileNavigatorWidget — the list of files in a commit above the diff blocks.

Wraps a FileListView and re-exposes its selection signals and file context
menu, so DiffWidget does not have to know the internal structure.
"""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QSize, Qt, Signal
from PySide6.QtWidgets import QListView, QMenu, QVBoxLayout, QWidget

from git_gui.presentation.models.diff_model import DiffModel
from git_gui.presentation.widgets.file_list_view import FileDeltaDelegate, FileListView


class FileNavigatorWidget(QWidget):
    file_history_requested = Signal(str)  # repo-relative path
    blame_requested = Signal(str)  # repo-relative path

    currentChanged = Signal(QModelIndex, QModelIndex)
    deselected = Signal()

    def __init__(self, model: DiffModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._model = model

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._list_view = FileListView(max_visible_rows=8)
        self._list_view.setEditTriggers(QListView.NoEditTriggers)
        self._list_view.setModel(model)
        self._list_view.setItemDelegate(FileDeltaDelegate(self._list_view))
        self._list_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list_view.customContextMenuRequested.connect(self._on_list_context_menu)
        layout.addWidget(self._list_view)

        # Without this, the parent slot keeps the empty-model height (~32px)
        # even after files are loaded.
        model.modelReset.connect(self.updateGeometry)

        self._list_view.selectionModel().currentChanged.connect(self.currentChanged.emit)
        self._list_view.deselected.connect(self.deselected.emit)

    @property
    def selection_model(self) -> QItemSelectionModel:
        return self._list_view.selectionModel()

    def sizeHint(self) -> QSize:
        return self._list_view.sizeHint()

    def minimumSizeHint(self) -> QSize:
        # Match sizeHint: a QScrollArea sizes its widget from minimumSizeHint,
        # and anything smaller collapses the list to a single row.
        return self._list_view.minimumSizeHint()

    def _show_file_menu(self, global_pos, path: str) -> None:
        menu = QMenu(self)
        history_action = menu.addAction("Show file history")
        blame_action = menu.addAction("Blame this file")
        chosen = menu.exec(global_pos)
        if chosen is history_action:
            self.file_history_requested.emit(path)
        elif chosen is blame_action:
            self.blame_requested.emit(path)

    def _on_list_context_menu(self, pos) -> None:
        index = self._list_view.indexAt(pos)
        if not index.isValid():
            return
        fs = self._model.data(index, Qt.UserRole)
        if fs is None:
            return
        self._show_file_menu(self._list_view.viewport().mapToGlobal(pos), fs.path)
