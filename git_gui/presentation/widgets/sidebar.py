# git_gui/presentation/widgets/sidebar.py
from __future__ import annotations
import threading
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QMenu, QStyle, QStyleOptionViewItem, QTreeView, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import Branch, Stash, Tag
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.theme import get_theme_manager, connect_widget
from git_gui.resources import get_resource_path


def _head_bg() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("primary")


def _hover_bg() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("surface_variant")


_ROW_HEIGHT = 28
_IS_HEAD_ROLE = Qt.UserRole + 2
_TARGET_OID_ROLE = Qt.UserRole + 3

_CLOUD_ICON = None


def _get_cloud_icon() -> QIcon:
    global _CLOUD_ICON
    if _CLOUD_ICON is None:
        _CLOUD_ICON = QIcon(str(get_resource_path("arts") / "ic_cloud_done.svg"))
    return _CLOUD_ICON


class _SidebarTree(QTreeView):
    """QTreeView that paints full-row hover and HEAD highlight."""

    def drawRow(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        # Full-row HEAD highlight
        if index.data(_IS_HEAD_ROLE):
            painter.save()
            painter.fillRect(option.rect, _head_bg())
            painter.restore()
        # Full-row hover (match Qt's default hover color)
        elif option.state & QStyle.State_MouseOver:
            painter.save()
            hover_color = option.palette.highlight().color()
            hover_color.setAlpha(70)
            painter.fillRect(option.rect, hover_color)
            painter.restore()
        super().drawRow(painter, option, index)


class _LoadSignals(QObject):
    done = Signal(list, list, list, set)  # branches, stashes, tags, remote_tag_names


class SidebarWidget(QWidget):
    branch_checkout_requested = Signal(str)   # branch name
    branch_merge_requested = Signal(str)
    branch_rebase_requested = Signal(str)
    branch_delete_requested = Signal(str)
    branch_push_requested = Signal(str)
    fetch_requested = Signal(str)             # remote name
    branch_clicked = Signal(str)              # target oid
    stash_pop_requested = Signal(int)
    stash_apply_requested = Signal(int)
    stash_drop_requested = Signal(int)
    stash_clicked = Signal(str)              # stash oid
    tag_clicked = Signal(str)               # target oid
    tag_delete_requested = Signal(str)       # tag name
    tag_push_requested = Signal(str)         # tag name

    def __init__(self, queries: QueryBus, commands: CommandBus,
                 remote_tag_cache=None, repo_path: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands
        self._remote_tag_cache = remote_tag_cache
        self._repo_path = repo_path

        self._tree = _SidebarTree()
        self._tree.setHeaderHidden(True)
        self._tree.setMouseTracking(True)
        self._tree.setSelectionMode(QTreeView.NoSelection)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.clicked.connect(self._on_click)
        self._tree.doubleClicked.connect(self._on_double_click)

        self._model = QStandardItemModel()
        self._tree.setModel(self._model)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tree)
        connect_widget(self)

    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._commands = commands
        if queries is None:
            self._model.clear()
        else:
            self.reload()

    def clear_stash_selection(self) -> None:
        self._tree.clearSelection()
        self._tree.setCurrentIndex(self._model.index(-1, 0))

    def set_repo_path(self, path: str | None) -> None:
        self._repo_path = path

    def reload(self) -> None:
        queries = self._queries

        signals = _LoadSignals()
        signals.done.connect(self._on_load_done)
        self._load_signals = signals  # prevent GC

        cache = self._remote_tag_cache
        repo_path = self._repo_path

        def _worker():
            branches = queries.get_branches.execute()
            stashes = queries.get_stashes.execute()
            tags = queries.get_tags.execute()
            remote_tag_names: set[str] = set()
            if cache and repo_path:
                data = cache.load(repo_path)
                for names in data.values():
                    remote_tag_names.update(names)
            signals.done.emit(branches, stashes, tags, remote_tag_names)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_load_done(self, branches: list[Branch], stashes: list[Stash],
                      tags: list[Tag], remote_tag_names: set[str]) -> None:
        if self._queries is None:
            return

        self._model.clear()

        local = [b for b in branches if not b.is_remote]
        remote = [b for b in branches if b.is_remote]

        # Local branches — highlight HEAD
        local_header = QStandardItem("LOCAL BRANCHES")
        local_header.setEditable(False)
        local_header.setData("header", Qt.UserRole + 1)
        local_header.setSizeHint(QSize(0, _ROW_HEIGHT))
        for b in local:
            child = QStandardItem(b.name)
            child.setEditable(False)
            child.setData(b.name, Qt.UserRole)
            child.setData("branch", Qt.UserRole + 1)
            child.setData(b.target_oid, _TARGET_OID_ROLE)
            child.setSizeHint(QSize(0, _ROW_HEIGHT))
            if b.is_head:
                child.setData(True, _IS_HEAD_ROLE)
            local_header.appendRow(child)
        self._model.appendRow(local_header)

        # Remote branches
        self._add_section("REMOTE BRANCHES", [
            (b.name, b.name, "remote_branch", b.target_oid) for b in remote
        ])

        # Stashes
        self._add_section("STASHES", [
            (s.message, str(s.index), "stash", s.oid) for s in stashes
        ])

        # Tags — with cloud icon for remote tags
        tag_header = QStandardItem("TAGS")
        tag_header.setEditable(False)
        tag_header.setData("header", Qt.UserRole + 1)
        tag_header.setSizeHint(QSize(0, _ROW_HEIGHT))
        for t in tags:
            child = QStandardItem(t.name)
            child.setEditable(False)
            child.setData(t.name, Qt.UserRole)
            child.setData("tag", Qt.UserRole + 1)
            child.setData(t.target_oid, _TARGET_OID_ROLE)
            child.setSizeHint(QSize(0, _ROW_HEIGHT))
            if t.name in remote_tag_names:
                child.setIcon(_get_cloud_icon())
            tag_header.appendRow(child)
        self._model.appendRow(tag_header)

        self._tree.expandAll()

    def _add_section(self, title: str, items: list[tuple]) -> None:
        header = QStandardItem(title)
        header.setEditable(False)
        header.setData("header", Qt.UserRole + 1)
        header.setSizeHint(QSize(0, _ROW_HEIGHT))
        for item in items:
            label, value, kind = item[0], item[1], item[2]
            oid = item[3] if len(item) > 3 else None
            child = QStandardItem(label)
            child.setEditable(False)
            child.setData(value, Qt.UserRole)
            child.setData(kind, Qt.UserRole + 1)
            if oid:
                child.setData(oid, _TARGET_OID_ROLE)
            child.setSizeHint(QSize(0, _ROW_HEIGHT))
            header.appendRow(child)
        self._model.appendRow(header)

    def _on_click(self, index) -> None:
        kind = index.data(Qt.UserRole + 1)
        oid = index.data(_TARGET_OID_ROLE)
        if kind == "stash" and oid:
            self.stash_clicked.emit(oid)
        elif kind == "tag" and oid:
            self.tag_clicked.emit(oid)
        elif oid:
            self.branch_clicked.emit(oid)

    def _on_double_click(self, index) -> None:
        kind = index.data(Qt.UserRole + 1)
        value = index.data(Qt.UserRole)
        if kind == "branch":
            self._commands.checkout.execute(value)
            self.branch_checkout_requested.emit(value)

    def _show_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        kind = index.data(Qt.UserRole + 1)
        value = index.data(Qt.UserRole)
        if kind not in ("branch", "remote_branch", "stash", "tag"):
            return
        menu = QMenu(self)
        if kind == "branch":
            menu.addAction("Checkout").triggered.connect(
                lambda: (self._commands.checkout.execute(value),
                         self.branch_checkout_requested.emit(value)))
            menu.addAction("Merge into current").triggered.connect(
                lambda: self.branch_merge_requested.emit(value))
            menu.addAction("Rebase onto").triggered.connect(
                lambda: self.branch_rebase_requested.emit(value))
            menu.addSeparator()
            menu.addAction("Push").triggered.connect(
                lambda: self.branch_push_requested.emit(value))
            menu.addSeparator()
            menu.addAction("Delete").triggered.connect(
                lambda: self.branch_delete_requested.emit(value))
        elif kind == "remote_branch":
            remote = value.split("/")[0]
            menu.addAction("Fetch").triggered.connect(
                lambda: self.fetch_requested.emit(remote))
        elif kind == "stash":
            idx = int(value)
            menu.addAction("Pop").triggered.connect(
                lambda: self.stash_pop_requested.emit(idx))
            menu.addAction("Apply").triggered.connect(
                lambda: self.stash_apply_requested.emit(idx))
            menu.addSeparator()
            menu.addAction("Drop").triggered.connect(
                lambda: self.stash_drop_requested.emit(idx))
        elif kind == "tag":
            menu.addAction("Push").triggered.connect(
                lambda: self.tag_push_requested.emit(value))
            menu.addSeparator()
            menu.addAction("Delete").triggered.connect(
                lambda: self.tag_delete_requested.emit(value))
        menu.exec(self._tree.viewport().mapToGlobal(pos))
