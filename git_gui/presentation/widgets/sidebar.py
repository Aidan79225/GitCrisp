from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QMenu,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from git_gui.domain.entities import Branch, Stash, Tag, split_remote_branch
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.theme import ColorRole, connect_widget, get_theme_manager
from git_gui.presentation.widgets.background import BackgroundRunner, start_daemon_thread
from git_gui.presentation.widgets.highlighting_tree import HighlightingTreeView
from git_gui.resources import get_resource_path

logger = logging.getLogger(__name__)


def _tag_sort_key(name: str) -> tuple[bool, list[int] | str]:
    raw = name.lstrip("vV")
    parts = raw.split(".")
    try:
        return (False, [int(p) for p in parts])
    except ValueError:
        return (True, name)


_ROW_HEIGHT = 28
_KIND_ROLE = Qt.UserRole + 1
_IS_HEAD_ROLE = Qt.UserRole + 2
_TARGET_OID_ROLE = Qt.UserRole + 3
# Tip of the branch's upstream, when it has one and it sits elsewhere than the
# local tip. Clicking the branch pushes it into the walk too, so a local branch
# that is behind still shows what its remote is holding ahead of it.
_UPSTREAM_OID_ROLE = Qt.UserRole + 4
_EPOCH = datetime.fromtimestamp(0, tz=UTC)


class _EntryKind(StrEnum):
    """What a row is, under _KIND_ROLE: it decides the row's menu and what
    clicking the row does.

    A StrEnum because the model stores it as a plain string and hands that
    back, which still compares equal to the member.
    """

    HEADER = "header"
    BRANCH = "branch"
    REMOTE_BRANCH = "remote_branch"
    STASH = "stash"
    TAG = "tag"


_BRANCH_KINDS = (_EntryKind.BRANCH, _EntryKind.REMOTE_BRANCH)


def _get_cloud_icon() -> QIcon:
    from PySide6.QtGui import QPainter, QPixmap

    path = str(get_resource_path("arts") / "ic_cloud_done.svg")
    src = QIcon(path).pixmap(16, 16)
    if src.isNull():
        return QIcon(path)
    color = get_theme_manager().current.colors.as_qcolor(ColorRole.ON_BACKGROUND)
    tinted = QPixmap(src.size())
    tinted.setDevicePixelRatio(src.devicePixelRatio())
    tinted.fill(Qt.transparent)
    p = QPainter(tinted)
    p.drawPixmap(0, 0, src)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(tinted.rect(), color)
    p.end()
    return QIcon(tinted)


def _row(label: str, value: str, kind: _EntryKind, oid: str | None) -> QStandardItem:
    """A sidebar entry: its menu acts on *value*; a click shows commit *oid*."""
    row = QStandardItem(label)
    row.setEditable(False)
    row.setData(value, Qt.UserRole)
    row.setData(kind, _KIND_ROLE)
    if oid:
        row.setData(oid, _TARGET_OID_ROLE)
    row.setSizeHint(QSize(0, _ROW_HEIGHT))
    return row


class _LoadSignals(QObject):
    # generation, branches, stashes, tags, remote_tag_names,
    # {local branch: upstream shorthand}
    done = Signal(int, list, list, list, set, dict)
    failed = Signal(int, str)  # generation, message


def _read_sidebar_data(
    queries: QueryBus, cache, repo_path: str | None
) -> tuple[list[Branch], list[Stash], list[Tag], set[str], dict[str, str]]:
    """Everything the sidebar lists, read on the worker thread."""
    branches = queries.get_branches.execute()
    stashes = queries.get_stashes.execute()
    tags = queries.get_tags.execute()
    upstreams = {
        info.name: info.upstream
        for info in queries.list_local_branches_with_upstream.execute()
        if info.upstream
    }
    remote_tag_names: set[str] = set()
    if cache and repo_path:
        for names in cache.load(repo_path).values():
            remote_tag_names.update(names)
    return branches, stashes, tags, remote_tag_names, upstreams


class SidebarWidget(QWidget):
    checkout_branch_requested = Signal(str)  # local or remote branch name
    branch_merge_requested = Signal(str)
    branch_rebase_requested = Signal(str)
    branch_delete_requested = Signal(str)
    branch_push_requested = Signal(str)
    fetch_requested = Signal(str)  # remote name
    branch_clicked = Signal(str, list)  # target oid, extra tips (its upstream)
    stash_pop_requested = Signal(int)
    stash_apply_requested = Signal(int)
    stash_drop_requested = Signal(int)
    stash_clicked = Signal(str)  # stash oid
    tag_clicked = Signal(str)  # target oid
    tag_delete_requested = Signal(str)  # tag name
    tag_push_requested = Signal(str)  # tag name
    remote_branch_delete_requested = Signal(str, str)  # (remote, branch)
    checkout_in_new_worktree_requested = Signal(str)  # branch name
    load_failed = Signal(str)  # why branches, stashes and tags could not be listed

    def __init__(
        self,
        queries: QueryBus,
        commands: CommandBus,
        remote_tag_cache=None,
        repo_path: str | None = None,
        parent=None,
        *,
        run_in_background: BackgroundRunner = start_daemon_thread,
    ) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands
        self._remote_tag_cache = remote_tag_cache
        self._run_in_background = run_in_background
        self._repo_path = repo_path
        self._worktree_branches: set[str] = set()
        # Bumped by every reload. A load that finishes after a newer one was
        # started — a previous repo's, or a superseded F5 — is dropped.
        self._load_generation = 0

        self._tree = HighlightingTreeView(_IS_HEAD_ROLE)
        self._tree.setAccessibleName("Branches, tags and stashes")
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
            self._load_generation += 1  # drop whatever the closed repo is still loading
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
        self._load_generation += 1
        generation = self._load_generation

        signals = _LoadSignals()
        signals.done.connect(self._on_worker_done)
        signals.failed.connect(self._on_worker_failed)
        self._load_signals = signals  # prevent GC

        cache = self._remote_tag_cache
        repo_path = self._repo_path

        def _worker():
            try:
                loaded = _read_sidebar_data(queries, cache, repo_path)
            except Exception as e:
                logger.warning("Sidebar reload failed: %s", e)
                signals.failed.emit(generation, str(e))
                return
            signals.done.emit(generation, *loaded)

        self._run_in_background(_worker)

    def _on_worker_done(
        self,
        generation: int,
        branches: list[Branch],
        stashes: list[Stash],
        tags: list[Tag],
        remote_tag_names: set[str],
        upstreams: dict[str, str],
    ) -> None:
        if generation != self._load_generation:
            return
        self._on_load_done(branches, stashes, tags, remote_tag_names, upstreams)

    def _on_worker_failed(self, generation: int, message: str) -> None:
        if generation != self._load_generation:
            return
        # The rows on screen may be the previous repo's: clicking one would
        # send its oids to this repo's graph.
        self._model.clear()
        self.load_failed.emit(message)

    def _on_load_done(
        self,
        branches: list[Branch],
        stashes: list[Stash],
        tags: list[Tag],
        remote_tag_names: set[str],
        upstreams: dict[str, str],
    ) -> None:
        self._model.clear()
        local = [b for b in branches if not b.is_remote]
        remote = [b for b in branches if b.is_remote]
        self._add_local_branches(local, remote, upstreams)
        self._add_section(
            "REMOTE BRANCHES",
            [_row(b.name, b.name, _EntryKind.REMOTE_BRANCH, b.target_oid) for b in remote],
        )
        self._add_stashes(stashes)
        self._add_tags(tags, remote_tag_names)
        self._tree.expandAll()
        self._refresh_branch_badges()

    def _add_local_branches(
        self, local: list[Branch], remote: list[Branch], upstreams: dict[str, str]
    ) -> None:
        remote_oids = {b.name: b.target_oid for b in remote}
        rows = []
        for b in local:
            row = _row(b.name, b.name, _EntryKind.BRANCH, b.target_oid)
            upstream_oid = remote_oids.get(upstreams.get(b.name, ""))
            if upstream_oid and upstream_oid != b.target_oid:
                row.setData(upstream_oid, _UPSTREAM_OID_ROLE)
            if b.is_head:
                row.setData(True, _IS_HEAD_ROLE)
            rows.append(row)
        self._add_section("LOCAL BRANCHES", rows)

    def _add_stashes(self, stashes: list[Stash]) -> None:
        # A stash without a timestamp falls to the end.
        newest_first = sorted(stashes, key=lambda s: s.timestamp or _EPOCH, reverse=True)
        self._add_section(
            "STASHES",
            [_row(s.message, str(s.index), _EntryKind.STASH, s.oid) for s in newest_first],
        )

    def _add_tags(self, tags: list[Tag], remote_tag_names: set[str]) -> None:
        cloud_icon = _get_cloud_icon()
        rows = []
        for t in sorted(tags, key=lambda t: _tag_sort_key(t.name), reverse=True):
            row = _row(t.name, t.name, _EntryKind.TAG, t.target_oid)
            if t.name in remote_tag_names:
                row.setIcon(cloud_icon)
            rows.append(row)
        self._add_section("TAGS", rows)

    def _add_section(self, title: str, rows: list[QStandardItem]) -> None:
        header = QStandardItem(title)
        header.setEditable(False)
        header.setData(_EntryKind.HEADER, _KIND_ROLE)
        header.setSizeHint(QSize(0, _ROW_HEIGHT))
        for row in rows:
            header.appendRow(row)
        self._model.appendRow(header)

    def _on_click(self, index) -> None:
        kind = index.data(_KIND_ROLE)
        oid = index.data(_TARGET_OID_ROLE)
        if kind == _EntryKind.STASH and oid:
            self.stash_clicked.emit(oid)
        elif kind == _EntryKind.TAG and oid:
            self.tag_clicked.emit(oid)
        elif oid:
            upstream_oid = index.data(_UPSTREAM_OID_ROLE)
            self.branch_clicked.emit(oid, [upstream_oid] if upstream_oid else [])

    def _on_double_click(self, index) -> None:
        kind = index.data(_KIND_ROLE)
        value = index.data(Qt.UserRole)
        if kind in _BRANCH_KINDS and value:
            self.checkout_branch_requested.emit(value)

    def _show_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        kind = index.data(_KIND_ROLE)
        value = index.data(Qt.UserRole)
        if kind not in (*_BRANCH_KINDS, _EntryKind.STASH, _EntryKind.TAG):
            return
        menu = QMenu(self)
        if kind == _EntryKind.BRANCH:
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
        elif kind == _EntryKind.REMOTE_BRANCH:
            self._add_remote_branch_actions(menu, value)
        elif kind == _EntryKind.STASH:
            idx = int(value)
            menu.addAction("Pop").triggered.connect(lambda: self.stash_pop_requested.emit(idx))
            menu.addAction("Apply").triggered.connect(lambda: self.stash_apply_requested.emit(idx))
            menu.addSeparator()
            menu.addAction("Drop").triggered.connect(lambda: self.stash_drop_requested.emit(idx))
        elif kind == _EntryKind.TAG:
            menu.addAction("Push").triggered.connect(lambda: self.tag_push_requested.emit(value))
            menu.addSeparator()
            menu.addAction("Delete").triggered.connect(
                lambda: self.tag_delete_requested.emit(value)
            )
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _add_remote_branch_actions(self, menu: QMenu, name: str) -> None:
        remote, branch = split_remote_branch(name, self._remote_names())
        menu.addAction("Checkout").triggered.connect(
            lambda: self.checkout_branch_requested.emit(name)
        )
        menu.addAction("Fetch").triggered.connect(lambda: self.fetch_requested.emit(remote))
        menu.addSeparator()
        menu.addAction("Delete").triggered.connect(
            lambda: self.remote_branch_delete_requested.emit(remote, branch)
        )

    def _remote_names(self) -> list[str]:
        """The repo's remotes, or none when they cannot be listed.

        One remote with an invalid name in .git/config fails the whole
        listing. The branch name then splits at its first '/', which is right
        for every remote whose name holds none.
        """
        try:
            return [r.name for r in self._queries.list_remotes.execute()]
        except Exception as e:
            logger.warning("Listing remotes failed: %s", e)
            return []

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

    def trigger_branch_action(self, action: str, branch: str) -> None:
        if action == "checkout":
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
