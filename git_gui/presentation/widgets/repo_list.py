# git_gui/presentation/widgets/repo_list.py
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMenu, QPushButton,
    QStyledItemDelegate, QStyleOptionViewItem, QTreeView,
    QVBoxLayout, QWidget,
)
from git_gui.domain.ports import IRepoStore

_ACTIVE_BG = QColor("#264f78")
_IS_ACTIVE_ROLE = Qt.UserRole + 2


class _RepoItemDelegate(QStyledItemDelegate):
    """Paints full-row blue background for the active repo."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        if index.data(_IS_ACTIVE_ROLE):
            painter.save()
            bg_rect = option.rect.adjusted(-option.rect.x(), 0, 0, 0)
            painter.fillRect(bg_rect, _ACTIVE_BG)
            painter.restore()
        super().paint(painter, option, index)


class RepoListWidget(QWidget):
    repo_switch_requested = Signal(str)
    repo_open_requested = Signal(str)
    repo_close_requested = Signal(str)
    repo_remove_recent_requested = Signal(str)

    def __init__(self, repo_store: IRepoStore, parent=None) -> None:
        super().__init__(parent)
        self._store = repo_store

        # Header with "+" button
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(4, 4, 4, 0)
        title = QLabel("REPOSITORIES")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() - 1)
        title.setFont(title_font)
        header_layout.addWidget(title, 1)

        self._btn_add = QPushButton("+")
        self._btn_add.setFixedSize(22, 22)
        self._btn_add.setToolTip("Open Repository...")
        self._btn_add.clicked.connect(self._on_add_clicked)
        header_layout.addWidget(self._btn_add)

        # Tree view
        self._tree = QTreeView()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.clicked.connect(self._on_item_clicked)

        self._model = QStandardItemModel()
        self._tree.setModel(self._model)
        self._tree.setItemDelegate(_RepoItemDelegate(self._tree))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header_layout)
        layout.addWidget(self._tree)

    def reload(self) -> None:
        self._model.clear()
        active = self._store.get_active()

        # Open repos section
        open_repos = self._store.get_open_repos()
        if open_repos:
            open_header = QStandardItem("OPEN")
            open_header.setEditable(False)
            open_header.setSelectable(False)
            open_header.setData("header", Qt.UserRole + 1)
            for path in open_repos:
                item = self._make_repo_item(path, "open", is_active=(path == active))
                open_header.appendRow(item)
            self._model.appendRow(open_header)

        # Recent repos section
        recent_repos = self._store.get_recent_repos()
        if recent_repos:
            recent_header = QStandardItem("RECENT")
            recent_header.setEditable(False)
            recent_header.setSelectable(False)
            recent_header.setData("header", Qt.UserRole + 1)
            for path in recent_repos:
                item = self._make_repo_item(path, "recent", is_active=False)
                recent_header.appendRow(item)
            self._model.appendRow(recent_header)

        self._tree.expandAll()

    def _make_repo_item(self, path: str, kind: str, is_active: bool) -> QStandardItem:
        display_name = Path(path).name
        item = QStandardItem(display_name)
        item.setEditable(False)
        item.setToolTip(path)
        item.setData(path, Qt.UserRole)
        item.setData(kind, Qt.UserRole + 1)
        if is_active:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setData(True, _IS_ACTIVE_ROLE)
        return item

    def _on_item_clicked(self, index) -> None:
        kind = index.data(Qt.UserRole + 1)
        path = index.data(Qt.UserRole)
        if kind == "open" and path:
            self.repo_switch_requested.emit(path)
        elif kind == "recent" and path:
            self.repo_open_requested.emit(path)

    def _show_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        kind = index.data(Qt.UserRole + 1)
        path = index.data(Qt.UserRole)

        menu = QMenu(self)
        if kind == "open" and path:
            menu.addAction("Close").triggered.connect(
                lambda: self.repo_close_requested.emit(path))
        elif kind == "recent" and path:
            menu.addAction("Remove from recent").triggered.connect(
                lambda: self.repo_remove_recent_requested.emit(path))
        elif kind == "header":
            title = index.data(Qt.DisplayRole)
            if title == "OPEN":
                menu.addAction("Open Repository...").triggered.connect(self._on_add_clicked)
            else:
                return
        else:
            return
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _on_add_clicked(self) -> None:
        dialog = QFileDialog(self)
        dialog.setWindowTitle("Open Repository")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        if dialog.exec() == QFileDialog.Accepted:
            dirs = dialog.selectedFiles()
            if dirs:
                self.repo_open_requested.emit(dirs[0])
