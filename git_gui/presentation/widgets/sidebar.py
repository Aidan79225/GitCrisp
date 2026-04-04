# git_gui/presentation/widgets/sidebar.py
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QMenu, QTreeView, QVBoxLayout, QWidget
from git_gui.presentation.bus import CommandBus, QueryBus


class SidebarWidget(QWidget):
    branch_checkout_requested = Signal(str)   # branch name
    branch_merge_requested = Signal(str)
    branch_rebase_requested = Signal(str)
    branch_delete_requested = Signal(str)
    branch_push_requested = Signal(str)
    fetch_requested = Signal(str)             # remote name

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
        self._model.clear()
        branches = self._queries.get_branches.execute()
        stashes = self._queries.get_stashes.execute()

        local = [b for b in branches if not b.is_remote]
        remote = [b for b in branches if b.is_remote]

        self._add_section("LOCAL BRANCHES", [
            (b.name, b.name, "branch") for b in local
        ])
        self._add_section("REMOTE BRANCHES", [
            (b.name, b.name, "remote_branch") for b in remote
        ])
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
        if kind not in ("branch", "remote_branch"):
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
        menu.exec(self._tree.viewport().mapToGlobal(pos))
