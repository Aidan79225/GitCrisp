# git_gui/presentation/widgets/graph.py
from __future__ import annotations
import threading
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QModelIndex, QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QMenu, QPushButton, QStyle,
    QStyleOptionViewItem, QTableView, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import Branch, Commit, WORKING_TREE_OID
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.graph_model import GraphModel
from git_gui.presentation.widgets.graph_lane_delegate import GraphLaneDelegate, LANE_W
from git_gui.presentation.widgets.commit_info_delegate import (
    CommitInfoDelegate, BADGE_GAP, BADGE_H_PAD, CELL_PAD,
)


PAGE_SIZE = 50


class _GraphTableView(QTableView):
    """QTableView with full-row hover highlight."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._hover_row = -1

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.pos())
        old = self._hover_row
        self._hover_row = index.row() if index.isValid() else -1
        if old != self._hover_row:
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_row = -1
        self.viewport().update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        if self._hover_row >= 0:
            from PySide6.QtGui import QPainter
            painter = QPainter(self.viewport())
            row_rect = self.visualRect(self.model().index(self._hover_row, 0))
            # Extend to full row width
            row_rect.setLeft(0)
            row_rect.setRight(self.viewport().width())
            row_rect.setHeight(self.rowHeight(self._hover_row))
            hover_color = self.palette().highlight().color()
            hover_color.setAlpha(30)
            painter.fillRect(row_rect, hover_color)
            painter.end()
        super().paintEvent(event)


class _LoadSignals(QObject):
    reload_done = Signal(list, list, bool, str)  # commits, branches, is_dirty, head_oid
    append_done = Signal(list, list)             # more_commits, branches


_ARTS = Path(__file__).resolve().parent.parent.parent / "arts"
_BTN_STYLE = (
    "QPushButton { border: none; border-radius: 4px; min-width: 36px; min-height: 36px; }"
    "QPushButton:hover { background-color: rgba(255, 255, 255, 30); }"
)


class GraphWidget(QWidget):
    commit_selected = Signal(str)  # emits oid (or WORKING_TREE_OID)
    create_branch_requested = Signal(str)       # oid
    checkout_commit_requested = Signal(str)      # oid
    checkout_branch_requested = Signal(str)      # branch name (local or remote)
    delete_branch_requested = Signal(str)        # local branch name
    reload_requested = Signal()
    push_requested = Signal()
    pull_requested = Signal()
    fetch_all_requested = Signal()

    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._loaded_count = 0  # how many commits loaded (excluding synthetic)
        self._has_more = True
        self._loading = False
        self._pending_scroll_oid: str | None = None

        self._view = _GraphTableView()
        self._view.setSelectionBehavior(QTableView.SelectRows)
        self._view.setSelectionMode(QTableView.SingleSelection)
        self._view.setShowGrid(False)
        self._view.verticalHeader().setVisible(False)
        self._view.setEditTriggers(QTableView.NoEditTriggers)

        # Hide column header — "Graph" / "Info" labels add no value
        self._view.horizontalHeader().setVisible(False)

        # Row height: 2 header rows + up to 3 message lines + padding
        fm = self._view.fontMetrics()
        self._view.verticalHeader().setDefaultSectionSize(fm.height() * 5 + 24)

        # Delegates
        self._view.setItemDelegateForColumn(0, GraphLaneDelegate(self._view))
        self._view.setItemDelegateForColumn(1, CommitInfoDelegate(self._view))

        self._model = GraphModel([], {})
        self._view.setModel(self._model)

        # Column widths — col 0 fixed, col 1 stretches with splitter
        header = self._view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self._view.setColumnWidth(0, LANE_W)
        self._view.selectionModel().currentRowChanged.connect(self._on_row_changed)

        self._view.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._show_context_menu)

        # Header bar with action buttons
        header_bar = QHBoxLayout()
        header_bar.setContentsMargins(4, 4, 4, 4)
        header_bar.addStretch()
        for icon_name, tooltip, signal in [
            ("ic_reload", "Reload (F5)", self.reload_requested),
            ("ic_push", "Push", self.push_requested),
            ("ic_pull", "Pull", self.pull_requested),
            ("ic_fetch", "Fetch All --prune", self.fetch_all_requested),
        ]:
            btn = QPushButton()
            btn.setIcon(QIcon(str(_ARTS / f"{icon_name}.svg")))
            btn.setIconSize(QSize(28, 28))
            btn.setToolTip(tooltip)
            btn.setStyleSheet(_BTN_STYLE)
            btn.clicked.connect(signal.emit)
            header_bar.addWidget(btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header_bar)
        layout.addWidget(self._view)

    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        if queries is None:
            self._model.reload([], {})
        else:
            self.reload()

    def reload(self) -> None:
        if self._loading:
            return
        self._loading = True
        queries = self._queries

        signals = _LoadSignals()
        signals.reload_done.connect(self._on_reload_done)
        self._load_signals = signals  # prevent GC

        def _worker():
            commits = queries.get_commit_graph.execute(limit=PAGE_SIZE)
            branches = queries.get_branches.execute()
            dirty = queries.is_dirty.execute()
            head_oid = queries.get_head_oid.execute() or ""
            signals.reload_done.emit(commits, branches, dirty, head_oid)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_reload_done(self, commits: list[Commit], branches: list[Branch],
                        is_dirty: bool, head_oid: str) -> None:
        self._loading = False
        if self._queries is None:
            return

        self._loaded_count = len(commits)
        self._has_more = len(commits) == PAGE_SIZE

        refs: dict[str, list[str]] = {}
        head_branch: str | None = None
        for b in branches:
            refs.setdefault(b.target_oid, []).append(b.name)
            if b.is_head and not b.is_remote:
                head_branch = b.name

        # Show HEAD badge only when detached (no local branch is HEAD)
        if head_oid and not head_branch:
            refs.setdefault(head_oid, []).insert(0, "HEAD")

        all_commits = list(commits)
        if is_dirty:
            synthetic = Commit(
                oid=WORKING_TREE_OID,
                message="Uncommitted Changes",
                author="",
                timestamp=datetime.now(),
                parents=[all_commits[0].oid] if all_commits else [],
            )
            all_commits.insert(0, synthetic)

        self._model.reload(all_commits, refs, head_branch)

        # Auto-fit graph column width to the max lane count
        max_lanes = max(
            (self._model.data(self._model.index(r, 0), Qt.UserRole + 1).n_lanes
             for r in range(self._model.rowCount())),
            default=1,
        )
        self._view.setColumnWidth(0, max_lanes * LANE_W + LANE_W)

        # Auto-fit info column minimum width to content
        fm = self._view.fontMetrics()
        gap = CELL_PAD * 2
        spacing = fm.horizontalAdvance("  ")  # space between left/right items
        min_info_w = 0
        for r in range(self._model.rowCount()):
            info = self._model.data(self._model.index(r, 1), Qt.UserRole + 1)
            if info is None:
                continue
            author = info.author.split("<")[0].strip() if "<" in info.author else info.author
            # Row 1: author + timestamp
            w1 = fm.horizontalAdvance(author) + fm.horizontalAdvance(info.timestamp) + spacing
            # Row 2: badges + hash
            badges_w = sum(
                fm.horizontalAdvance(n) + BADGE_H_PAD * 2 + BADGE_GAP
                for n in info.branch_names
            )
            w2 = badges_w + fm.horizontalAdvance(info.short_oid) + spacing
            min_info_w = max(min_info_w, w1, w2)

        min_info_w += gap
        graph_w = max_lanes * LANE_W + LANE_W
        self._view.setMinimumWidth(graph_w + min_info_w)

        if self._pending_scroll_oid:
            self.scroll_to_oid(self._pending_scroll_oid)
            self._pending_scroll_oid = None

    def _on_scroll(self, value: int) -> None:
        scrollbar = self._view.verticalScrollBar()
        if self._has_more and not self._loading and value >= scrollbar.maximum() - 1:
            self._load_more()

    def _load_more(self) -> None:
        self._loading = True
        queries = self._queries
        skip = self._loaded_count

        signals = _LoadSignals()
        signals.append_done.connect(self._on_append_done)
        self._load_signals = signals  # prevent GC

        def _worker():
            more = queries.get_commit_graph.execute(limit=PAGE_SIZE, skip=skip)
            branches = queries.get_branches.execute()
            signals.append_done.emit(more, branches)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_append_done(self, more: list[Commit], branches: list[Branch]) -> None:
        self._loading = False
        if self._queries is None:
            return

        if not more:
            self._has_more = False
            return

        self._has_more = len(more) == PAGE_SIZE
        self._loaded_count += len(more)

        refs: dict[str, list[str]] = {}
        for b in branches:
            refs.setdefault(b.target_oid, []).append(b.name)

        self._model.append(more, refs)

    def _show_context_menu(self, pos) -> None:
        index = self._view.indexAt(pos)
        if not index.isValid():
            return
        oid = self._model.data(self._model.index(index.row(), 0), Qt.UserRole)
        if not oid or oid == WORKING_TREE_OID:
            return

        info = self._model.data(self._model.index(index.row(), 1), Qt.UserRole + 1)
        branch_names = info.branch_names if info else []

        menu = QMenu(self)

        menu.addAction("Create Branch").triggered.connect(
            lambda: self.create_branch_requested.emit(oid))
        menu.addAction("Checkout (detached HEAD)").triggered.connect(
            lambda: self.checkout_commit_requested.emit(oid))

        # Filter out HEAD pseudo-ref for branch operations
        real_branches = [n for n in branch_names if n != "HEAD"]
        local_branches = [n for n in real_branches if "/" not in n]

        if real_branches:
            menu.addSeparator()
            if len(real_branches) == 1:
                name = real_branches[0]
                menu.addAction(f"Checkout branch: {name}").triggered.connect(
                    lambda: self.checkout_branch_requested.emit(name))
            else:
                sub = menu.addMenu("Checkout branch")
                for name in real_branches:
                    sub.addAction(name).triggered.connect(
                        lambda _checked=False, n=name: self.checkout_branch_requested.emit(n))

        if local_branches:
            if len(local_branches) == 1:
                name = local_branches[0]
                menu.addAction(f"Delete branch: {name}").triggered.connect(
                    lambda: self.delete_branch_requested.emit(name))
            else:
                sub = menu.addMenu("Delete branch")
                for name in local_branches:
                    sub.addAction(name).triggered.connect(
                        lambda _checked=False, n=name: self.delete_branch_requested.emit(n))

        menu.exec(self._view.viewport().mapToGlobal(pos))

    def reload_and_scroll_to(self, oid: str) -> None:
        """Reload and scroll to the given oid after load completes."""
        self._pending_scroll_oid = oid
        self.reload()

    def scroll_to_oid(self, oid: str) -> None:
        """Scroll so the row with the given oid is the first visible item."""
        for row in range(self._model.rowCount()):
            row_oid = self._model.data(self._model.index(row, 0), Qt.UserRole)
            if row_oid == oid:
                index = self._model.index(row, 0)
                self._view.scrollTo(index, QTableView.PositionAtTop)
                return

    def _on_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        oid = self._model.data(self._model.index(current.row(), 0), Qt.UserRole)
        if oid:
            self.commit_selected.emit(oid)
