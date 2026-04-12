# git_gui/presentation/widgets/repo_list.py
from __future__ import annotations
from pathlib import Path
import pygit2
from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeView,
    QVBoxLayout, QWidget,
)
from git_gui.domain.ports import IRepoStore
from git_gui.presentation.theme import get_theme_manager, connect_widget


def _active_bg() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("primary")


def _display_path(path: str) -> str:
    """Convert an absolute repo path into a display-friendly form.

    Paths under the user's home directory are shortened with ``~``.
    All returned paths use forward slashes, regardless of OS.
    """
    p = Path(path)
    try:
        rel = p.relative_to(Path.home())
    except ValueError:
        return p.as_posix()
    if rel == Path("."):
        return "~"
    return "~/" + rel.as_posix()


_IS_ACTIVE_ROLE = Qt.UserRole + 2
_ROW_HEIGHT = 28


class _RepoTree(QTreeView):
    """QTreeView that paints full-row hover and active repo highlight.

    Implements manual drag-and-drop reordering for OPEN section items.
    Uses Qt's drag detection (setDragEnabled) but overrides startDrag
    and dropEvent so we control the data and the reorder logic.
    """

    repo_reorder_requested = Signal(str, int)  # (path, target_row)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from PySide6.QtCore import QPersistentModelIndex
        self._hover_idx = QPersistentModelIndex()

    def startDrag(self, supportedActions) -> None:
        """Override Qt's drag start to use our own mime data (repo path as text)."""
        idx = self.currentIndex()
        if not idx.isValid() or idx.data(Qt.UserRole + 1) != "open":
            return
        path = idx.data(Qt.UserRole)
        if not path:
            return
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QDrag
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(path)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasText():
            return
        dragged_path = event.mimeData().text()
        drop_idx = self.indexAt(event.position().toPoint())
        if not drop_idx.isValid():
            return
        # Only allow drop within the OPEN section
        if drop_idx.data(Qt.UserRole + 1) not in ("open", "header"):
            return
        if drop_idx.data(Qt.UserRole + 1) == "header":
            target_row = 0
        else:
            target_row = drop_idx.row()
        self.repo_reorder_requested.emit(dragged_path, target_row)
        event.acceptProposedAction()

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

    def drawBranches(self, painter, rect, index) -> None:
        if index.data(_IS_ACTIVE_ROLE):
            painter.fillRect(rect, _active_bg())
        elif self._hover_idx.isValid() and index == self._hover_idx:
            painter.fillRect(
                rect,
                get_theme_manager().current.colors.as_qcolor("surface_container_high"),
            )
        super().drawBranches(painter, rect, index)

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


_REPO_ROW_HEIGHT = 40
_ROW_H_PADDING = 8


class _RepoItemDelegate(QStyledItemDelegate):
    """Two-line item delegate for repo rows.

    Line 1: the repo name (Path.name), default font.
    Line 2: _display_path(path), smaller font, dimmer color, middle-elided.

    Header rows (marked with "header" in Qt.UserRole + 1) keep their default
    rendering by deferring to super().paint/sizeHint.
    """

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        if index.data(Qt.UserRole + 1) == "header":
            return super().sizeHint(option, index)
        return QSize(option.rect.width(), _REPO_ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        if index.data(Qt.UserRole + 1) == "header":
            super().paint(painter, option, index)
            return

        path = index.data(Qt.UserRole)
        if not path:
            super().paint(painter, option, index)
            return

        name = Path(path).name
        disp = _display_path(path)
        is_active = bool(index.data(_IS_ACTIVE_ROLE))

        colors = get_theme_manager().current.colors
        name_color = colors.as_qcolor("on_primary") if is_active else colors.as_qcolor("on_surface")
        path_color = colors.as_qcolor("on_surface_variant")

        rect = option.rect
        text_left = rect.left() + _ROW_H_PADDING
        text_right = rect.right() - _ROW_H_PADDING
        text_width = max(0, text_right - text_left)

        # Top half: repo name
        name_font = QFont(option.font)
        if is_active:
            name_font.setBold(True)
        name_metrics = QFontMetrics(name_font)
        name_height = name_metrics.height()
        name_top = rect.top() + (rect.height() // 2) - name_height
        name_rect = QRect(text_left, name_top, text_width, name_height)

        painter.save()
        painter.setFont(name_font)
        painter.setPen(name_color)
        elided_name = name_metrics.elidedText(name, Qt.ElideMiddle, text_width)
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_name)

        # Bottom half: display path
        path_font = QFont(option.font)
        path_font.setPointSizeF(max(1.0, path_font.pointSizeF() * 0.85))
        path_metrics = QFontMetrics(path_font)
        path_height = path_metrics.height()
        path_top = name_rect.bottom() + 2
        path_rect = QRect(text_left, path_top, text_width, path_height)

        painter.setFont(path_font)
        painter.setPen(path_color)
        elided_path = path_metrics.elidedText(disp, Qt.ElideMiddle, text_width)
        painter.drawText(path_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_path)

        painter.restore()


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
            "QPushButton:hover { background: palette(alternate-base); } "
            "QPushButton:pressed { background: palette(highlight); color: palette(highlighted-text); }"
        )
        self._btn_add.setToolTip("Open Repository...")
        self._btn_add.clicked.connect(self._on_add_clicked)

        self._btn_clone = QPushButton("Clone")
        self._btn_clone.setFixedHeight(28)
        self._btn_clone.setStyleSheet(
            "QPushButton { padding: 4px 10px; border: none; "
            "border-radius: 4px; background: palette(button); } "
            "QPushButton:hover { background: palette(alternate-base); } "
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
        self._tree.setDragEnabled(True)
        self._tree.setAcceptDrops(True)
        self._tree.viewport().setAttribute(Qt.WA_Hover, True)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.clicked.connect(self._on_item_clicked)

        self._model = QStandardItemModel()
        self._tree.repo_reorder_requested.connect(self._on_repo_reorder)
        self._tree.setModel(self._model)
        self._tree.setItemDelegate(_RepoItemDelegate(self._tree))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header_layout)
        layout.addWidget(self._tree)

        connect_widget(self)

    def reload(self) -> None:
        self._model.clear()
        active = self._store.get_active()

        # Open repos section (drag-and-drop reorderable via custom DnD)
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

        # Recent repos section (not reorderable)
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
        if is_active:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setData(True, _IS_ACTIVE_ROLE)
        return item

    def _on_repo_reorder(self, path: str, target_row: int) -> None:
        """Move *path* to *target_row* within the open repos list and reload."""
        current = self._store.get_open_repos()
        if path not in current:
            return
        current.remove(path)
        current.insert(target_row, path)
        self._store.set_open_order(current)
        self._store.save()
        self.reload()

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
        while True:
            dialog = QFileDialog(self)
            dialog.setWindowTitle("Open Repository")
            dialog.setFileMode(QFileDialog.Directory)
            dialog.setOption(QFileDialog.ShowDirsOnly, True)
            if dialog.exec() != QFileDialog.Accepted:
                return
            dirs = dialog.selectedFiles()
            if not dirs:
                return
            path = dirs[0]
            if pygit2.discover_repository(path) is not None:
                self.repo_open_requested.emit(path)
                return
            QMessageBox.warning(
                self,
                "Not a Git Repository",
                "The selected folder is not a Git repository.\n"
                "Please choose a folder that contains a Git repository.",
            )
