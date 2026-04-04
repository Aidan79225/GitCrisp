# git_gui/presentation/widgets/sidebar.py
from __future__ import annotations
import threading
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QMenu, QStyledItemDelegate, QStyleOptionViewItem, QTreeView,
    QVBoxLayout, QWidget,
)
from git_gui.domain.entities import Branch, Stash
from git_gui.presentation.bus import CommandBus, QueryBus

_HEAD_BG = QColor("#264f78")
_ROW_HEIGHT = 28
_IS_HEAD_ROLE = Qt.UserRole + 2


class _BranchDelegate(QStyledItemDelegate):
    """Paints full-row blue background for HEAD branch."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        if index.data(_IS_HEAD_ROLE):
            painter.save()
            bg_rect = option.rect.adjusted(-option.rect.x(), 0, 0, 0)
            painter.fillRect(bg_rect, _HEAD_BG)
            painter.restore()
        super().paint(painter, option, index)


class _LoadSignals(QObject):
    done = Signal(list, list)  # branches, stashes


class SidebarWidget(QWidget):
    branch_checkout_requested = Signal(str)   # branch name
    branch_merge_requested = Signal(str)
    branch_rebase_requested = Signal(str)
    branch_delete_requested = Signal(str)
    branch_push_requested = Signal(str)
    fetch_requested = Signal(str)             # remote name
    stash_pop_requested = Signal(int)
    stash_apply_requested = Signal(int)
    stash_drop_requested = Signal(int)

    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands

        self._tree = QTreeView()
        self._tree.setHeaderHidden(True)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.doubleClicked.connect(self._on_double_click)

        self._model = QStandardItemModel()
        self._tree.setModel(self._model)
        self._tree.setItemDelegate(_BranchDelegate(self._tree))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tree)

    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._commands = commands
        if queries is None:
            self._model.clear()
        else:
            self.reload()

    def reload(self) -> None:
        queries = self._queries

        signals = _LoadSignals()
        signals.done.connect(self._on_load_done)
        self._load_signals = signals  # prevent GC

        def _worker():
            branches = queries.get_branches.execute()
            stashes = queries.get_stashes.execute()
            signals.done.emit(branches, stashes)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_load_done(self, branches: list[Branch], stashes: list[Stash]) -> None:
        if self._queries is None:
            return

        self._model.clear()

        local = [b for b in branches if not b.is_remote]
        remote = [b for b in branches if b.is_remote]

        # Local branches — highlight HEAD
        local_header = QStandardItem("LOCAL BRANCHES")
        local_header.setEditable(False)
        local_header.setData("header", Qt.UserRole + 1)
        for b in local:
            child = QStandardItem(b.name)
            child.setEditable(False)
            child.setData(b.name, Qt.UserRole)
            child.setData("branch", Qt.UserRole + 1)
            child.setSizeHint(QSize(0, _ROW_HEIGHT))
            if b.is_head:
                child.setData(True, _IS_HEAD_ROLE)
            local_header.appendRow(child)
        self._model.appendRow(local_header)

        # Remote branches
        self._add_section("REMOTE BRANCHES", [
            (b.name, b.name, "remote_branch") for b in remote
        ])

        # Stashes
        self._add_section("STASHES", [
            (s.message, str(s.index), "stash") for s in stashes
        ])

        self._tree.expandAll()

    def _add_section(self, title: str, items: list[tuple[str, str, str]]) -> None:
        header = QStandardItem(title)
        header.setEditable(False)
        header.setData("header", Qt.UserRole + 1)
        for label, value, kind in items:
            child = QStandardItem(label)
            child.setEditable(False)
            child.setData(value, Qt.UserRole)
            child.setData(kind, Qt.UserRole + 1)
            child.setSizeHint(QSize(0, _ROW_HEIGHT))
            header.appendRow(child)
        self._model.appendRow(header)

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
        if kind not in ("branch", "remote_branch", "stash"):
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
        menu.exec(self._tree.viewport().mapToGlobal(pos))
