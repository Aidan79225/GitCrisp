# git_gui/presentation/widgets/sidebar.py
from __future__ import annotations

import threading
from datetime import UTC

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QMenu,
    QStyleOptionViewItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from git_gui.domain.entities import Branch, Stash, Tag
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.theme import connect_widget, get_theme_manager
from git_gui.resources import get_resource_path


def _tag_sort_key(name: str) -> tuple[bool, list[int] | str]:
    raw = name.lstrip("vV")
    parts = raw.split(".")
    try:
        return (False, [int(p) for p in parts])
    except ValueError:
        return (True, name)


def _head_bg() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("primary")


def _hover_bg() -> QColor:
    return get_theme_manager().current.colors.as_qcolor("surface_variant")


_ROW_HEIGHT = 28
_IS_HEAD_ROLE = Qt.UserRole + 2
_TARGET_OID_ROLE = Qt.UserRole + 3


def _get_cloud_icon() -> QIcon:
    from PySide6.QtGui import QPainter, QPixmap

    path = str(get_resource_path("arts") / "ic_cloud_done.svg")
    src = QIcon(path).pixmap(16, 16)
    if src.isNull():
        return QIcon(path)
    color = get_theme_manager().current.colors.as_qcolor("on_background")
    tinted = QPixmap(src.size())
    tinted.setDevicePixelRatio(src.devicePixelRatio())
    tinted.fill(Qt.transparent)
    p = QPainter(tinted)
    p.drawPixmap(0, 0, src)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(tinted.rect(), color)
    p.end()
    return QIcon(tinted)


class _SidebarTree(QTreeView):
    """QTreeView that paints full-row hover and HEAD highlight."""

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

    def drawBranches(self, painter, rect, index) -> None:
        if index.data(_IS_HEAD_ROLE):
            painter.fillRect(rect, _head_bg())
        elif self._hover_idx.isValid() and index == self._hover_idx:
            painter.fillRect(
                rect,
                get_theme_manager().current.colors.as_qcolor("surface_container_high"),
            )
        super().drawBranches(painter, rect, index)

    def drawRow(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        # Full-row HEAD highlight
        if index.data(_IS_HEAD_ROLE):
            painter.save()
            painter.fillRect(option.rect, _head_bg())
            painter.restore()
        elif self._hover_idx.isValid() and index == self._hover_idx:
            painter.save()
            hover_color = get_theme_manager().current.colors.as_qcolor("surface_container_high")
            painter.fillRect(option.rect, hover_color)
            painter.restore()
        super().drawRow(painter, option, index)


class _LoadSignals(QObject):
    done = Signal(list, list, list, set)  # branches, stashes, tags, remote_tag_names


class SidebarWidget(QWidget):
    checkout_branch_requested = Signal(str)  # local or remote branch name
    branch_merge_requested = Signal(str)
    branch_rebase_requested = Signal(str)
    branch_delete_requested = Signal(str)
    branch_push_requested = Signal(str)
    fetch_requested = Signal(str)  # remote name
    branch_clicked = Signal(str)  # target oid
    stash_pop_requested = Signal(int)
    stash_apply_requested = Signal(int)
    stash_drop_requested = Signal(int)
    stash_clicked = Signal(str)  # stash oid
    tag_clicked = Signal(str)  # target oid
    tag_delete_requested = Signal(str)  # tag name
    tag_push_requested = Signal(str)  # tag name
    remote_branch_delete_requested = Signal(str, str)  # (remote, branch)
    checkout_in_new_worktree_requested = Signal(str)  # branch name

    def __init__(
        self,
        queries: QueryBus,
        commands: CommandBus,
        remote_tag_cache=None,
        repo_path: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands
        self._remote_tag_cache = remote_tag_cache
        self._repo_path = repo_path
        self._worktree_branches: set[str] = set()
        self._smart_checkout = None

        self._tree = _SidebarTree()
        self._tree.setHeaderHidden(True)
        self._tree.setMouseTracking(True)
        self._tree.viewport().setAttribute(Qt.WA_Hover, True)
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

    def _on_load_done(
        self,
        branches: list[Branch],
        stashes: list[Stash],
        tags: list[Tag],
        remote_tag_names: set[str],
    ) -> None:
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
        self._add_section(
            "REMOTE BRANCHES", [(b.name, b.name, "remote_branch", b.target_oid) for b in remote]
        )

        # Stashes — most recent first. Stashes without a timestamp fall to the end.
        from datetime import datetime

        _stash_epoch = datetime.fromtimestamp(0, tz=UTC)
        stashes_sorted = sorted(
            stashes,
            key=lambda s: s.timestamp or _stash_epoch,
            reverse=True,
        )
        self._add_section(
            "STASHES", [(s.message, str(s.index), "stash", s.oid) for s in stashes_sorted]
        )

        # Tags — sorted by name descending. Cloud icon for remote tags.
        tags_sorted = sorted(tags, key=lambda t: _tag_sort_key(t.name), reverse=True)
        tag_header = QStandardItem("TAGS")
        tag_header.setEditable(False)
        tag_header.setData("header", Qt.UserRole + 1)
        tag_header.setSizeHint(QSize(0, _ROW_HEIGHT))
        for t in tags_sorted:
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
        self._refresh_branch_badges()

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
        if kind in ("branch", "remote_branch") and value:
            self.checkout_branch_requested.emit(value)

    def _show_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        kind = index.data(Qt.UserRole + 1)
        value = index.data(Qt.UserRole)
        if kind not in ("branch", "remote_branch", "stash", "tag"):
            return
        menu = QMenu(self)
        if kind == "branch":
            for entry in self.build_branch_context_actions(value):
                a = menu.addAction(entry["label"])
                a.triggered.connect(
                    lambda _checked=False, e=entry: self.trigger_branch_action(
                        e["action"], e["branch"]
                    )
                )
                # Add separators between groups (matches the pre-existing menu shape).
                if entry["action"] in ("rebase", "push"):
                    menu.addSeparator()
        elif kind == "remote_branch":
            remote, branch = value.split("/", 1)
            menu.addAction("Checkout").triggered.connect(
                lambda: self.checkout_branch_requested.emit(value)
            )
            menu.addAction("Fetch").triggered.connect(lambda: self.fetch_requested.emit(remote))
            menu.addSeparator()
            menu.addAction("Delete").triggered.connect(
                lambda: self.remote_branch_delete_requested.emit(remote, branch)
            )
        elif kind == "stash":
            idx = int(value)
            menu.addAction("Pop").triggered.connect(lambda: self.stash_pop_requested.emit(idx))
            menu.addAction("Apply").triggered.connect(lambda: self.stash_apply_requested.emit(idx))
            menu.addSeparator()
            menu.addAction("Drop").triggered.connect(lambda: self.stash_drop_requested.emit(idx))
        elif kind == "tag":
            menu.addAction("Push").triggered.connect(lambda: self.tag_push_requested.emit(value))
            menu.addSeparator()
            menu.addAction("Delete").triggered.connect(
                lambda: self.tag_delete_requested.emit(value)
            )
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    # ── Worktree-awareness helpers ──────────────────────────────────────

    def set_worktree_branches(self, branches: set[str]) -> None:
        """Set the names of local branches currently checked out in a worktree.
        Rows for these branches render with a '+' badge in the label."""
        self._worktree_branches = set(branches)
        self._refresh_branch_badges()

    def has_worktree_badge(self, branch: str) -> bool:
        return branch in self._worktree_branches

    def build_branch_context_actions(self, branch: str) -> list[dict]:
        """Return the action list for the branch context menu. The existing
        Checkout/Merge/Rebase/Push/Delete entries plus the new worktree entry."""
        return [
            {"label": "Checkout", "action": "checkout", "branch": branch},
            {
                "label": "Checkout in New Worktree…",
                "action": "checkout_in_new_worktree",
                "branch": branch,
            },
            {"label": "Merge into current", "action": "merge", "branch": branch},
            {"label": "Rebase onto", "action": "rebase", "branch": branch},
            {"label": "Push", "action": "push", "branch": branch},
            {"label": "Delete", "action": "delete", "branch": branch},
        ]

    def set_smart_checkout(self, sc) -> None:
        """Route the sidebar's ``trigger_branch_action("checkout", ...)`` through
        SmartCheckout when set. Falls back to direct command if None."""
        self._smart_checkout = sc

    def trigger_branch_action(self, action: str, branch: str) -> None:
        """Emit the appropriate signal for the chosen branch action."""
        if action == "checkout":
            # Route through SmartCheckout if MainWindow has set one;
            # otherwise emit the standard checkout signal for MainWindow
            # to handle through the unified `_on_checkout_branch` flow.
            sc = self._smart_checkout
            if sc is not None:
                try:
                    sc.execute(branch)
                except Exception:
                    pass
            else:
                self.checkout_branch_requested.emit(branch)
        elif action == "checkout_in_new_worktree":
            self.checkout_in_new_worktree_requested.emit(branch)
        elif action == "merge":
            self.branch_merge_requested.emit(branch)
        elif action == "rebase":
            self.branch_rebase_requested.emit(branch)
        elif action == "push":
            self.branch_push_requested.emit(branch)
        elif action == "delete":
            self.branch_delete_requested.emit(branch)

    def _refresh_branch_badges(self) -> None:
        """Walk the LOCAL BRANCHES header and append/strip the '+' badge."""
        model = self._model
        for row in range(model.rowCount()):
            header = model.item(row)
            if header is None or header.text() != "LOCAL BRANCHES":
                continue
            for child_row in range(header.rowCount()):
                child = header.child(child_row)
                if child is None:
                    continue
                name = child.data(Qt.UserRole)
                if name is None:
                    continue
                if name in self._worktree_branches:
                    child.setText(f"{name}  +")
                    child.setToolTip("Checked out in a worktree")
                else:
                    child.setText(name)
                    child.setToolTip("")
            break
