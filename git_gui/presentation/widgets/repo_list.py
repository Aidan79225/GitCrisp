# git_gui/presentation/widgets/repo_list.py
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMenu, QPushButton,
    QStyle, QStyleOptionViewItem, QTreeView,
    QVBoxLayout, QWidget,
)
from git_gui.domain.ports import IRepoStore
from git_gui.presentation.theme import get_theme_manager, connect_widget


def _active_bg() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("primary")


_IS_ACTIVE_ROLE = Qt.UserRole + 2
_ROW_HEIGHT = 28


class _RepoTree(QTreeView):
    """QTreeView that paints full-row hover and active repo highlight."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from PySide6.QtCore import QPersistentModelIndex
        self._hover_idx = QPersistentModelIndex()

    def mouseMoveEvent(self, event) -> None:
        from PySide6.QtCore import QPersistentModelIndex
        idx = self.indexAt(event.position().toPoint())
        new_idx = QPersistentModelIndex(idx) if idx.isValid() else QPersistentModelIndex()
        if new_idx != self._hover_idx:
            self._hover_idx = new_idx
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        from PySide6.QtCore import QPersistentModelIndex
        if self._hover_idx.isValid():
            self._hover_idx = QPersistentModelIndex()
            self.viewport().update()
        super().leaveEvent(event)

    def drawRow(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        if index.data(_IS_ACTIVE_ROLE):
            painter.save()
            painter.fillRect(option.rect, _active_bg())
            painter.restore()
        elif self._hover_idx.isValid() and index == self._hover_idx:
            painter.save()
            painter.fillRect(
                option.rect,
                get_theme_manager().current.colors.as_qcolor("surface_container_high"),
            )
            painter.restore()
        super().drawRow(painter, option, index)


class RepoListWidget(QWidget):
    repo_switch_requested = Signal(str)
    repo_open_requested = Signal(str)
    repo_close_requested = Signal(str)
    repo_remove_recent_requested = Signal(str)
    clone_requested = Signal()

    def __init__(self, repo_store: IRepoStore, parent=None) -> None:
        super().__init__(parent)
        self._store = repo_store

        # Header with "+" button
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(4, 4, 4, 4)
        title = QLabel("REPOSITORIES")
        title.setFixedHeight(_ROW_HEIGHT)
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() - 1)
        title.setFont(title_font)
        header_layout.addWidget(title, 1)
        header_layout.addSpacing(8)

        self._btn_add = QPushButton("Open")
        self._btn_add.setFixedHeight(28)
        self._btn_add.setStyleSheet(
            "QPushButton { padding: 4px 10px; border: none; "
            "border-radius: 4px; background: palette(button); } "
            "QPushButton:hover { background: palette(midlight); } "
            "QPushButton:pressed { background: palette(highlight); color: palette(highlighted-text); }"
        )
        self._btn_add.setToolTip("Open Repository...")
        self._btn_add.clicked.connect(self._on_add_clicked)

        self._btn_clone = QPushButton("Clone")
        self._btn_clone.setFixedHeight(28)
        self._btn_clone.setStyleSheet(
            "QPushButton { padding: 4px 10px; border: none; "
            "border-radius: 4px; background: palette(button); } "
            "QPushButton:hover { background: palette(midlight); } "
            "QPushButton:pressed { background: palette(highlight); color: palette(highlighted-text); }"
        )
        self._btn_clone.setToolTip("Clone Repository...")
        self._btn_clone.clicked.connect(lambda: self.clone_requested.emit())
        header_layout.addWidget(self._btn_add)
        header_layout.addSpacing(6)
        header_layout.addWidget(self._btn_clone)

        # Tree view
        self._tree = _RepoTree()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setMouseTracking(True)
        self._tree.viewport().setAttribute(Qt.WA_Hover, True)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.clicked.connect(self._on_item_clicked)

        self._model = QStandardItemModel()
        self._tree.setModel(self._model)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header_layout)
        layout.addWidget(self._tree)

        connect_widget(self)

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
            open_header.setSizeHint(QSize(0, _ROW_HEIGHT))
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
            recent_header.setSizeHint(QSize(0, _ROW_HEIGHT))
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
        item.setSizeHint(QSize(0, _ROW_HEIGHT))
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
                menu.addAction("Clone Repository...").triggered.connect(
                    lambda: self.clone_requested.emit())
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
