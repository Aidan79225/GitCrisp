# git_gui/presentation/widgets/graph.py
from __future__ import annotations
import threading
from datetime import datetime
from git_gui.resources import get_resource_path
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


_ARTS = get_resource_path("arts")
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
    stash_requested = Signal()

    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._loaded_count = 0  # how many commits loaded (excluding synthetic)
        self._has_more = True
        self._loading = False
        self._reload_limit = PAGE_SIZE
        self._pending_scroll_oid: str | None = None
        self._extra_tips: list[str] | None = None

        self._view = _GraphTableView()
        self._view.setSelectionBehavior(QTableView.SelectRows)
        self._view.setSelectionMode(QTableView.SingleSelection)
        self._view.setShowGrid(False)
        self._view.verticalHeader().setVisible(False)
        self._view.setEditTriggers(QTableView.NoEditTriggers)

        # Hide column header — "Graph" / "Info" labels add no value
        self._view.horizontalHeader().setVisible(False)

        # Let delegates control row height via sizeHint
        self._view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        # Delegates
        self._view.setItemDelegateForColumn(0, GraphLaneDelegate(self._view))
        self._view.setItemDelegateForColumn(1, CommitInfoDelegate(self._view))

        self._model = GraphModel([], {})
        self._view.setModel(self._model)

        # Column widths — col 0 fixed by lane count, col 1 stretches to fill
        header = self._view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self._view.setColumnWidth(0, LANE_W)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.selectionModel().currentRowChanged.connect(self._on_row_changed)

        self._view.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._show_context_menu)

        # Header bar with action buttons
        header_bar = QHBoxLayout()
        header_bar.setContentsMargins(4, 4, 4, 4)
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

        header_bar.addStretch()

        self._stash_btn = QPushButton()
        self._stash_btn.setIcon(QIcon(str(_ARTS / "ic_stash.svg")))
        self._stash_btn.setIconSize(QSize(28, 28))
        self._stash_btn.setToolTip("Stash")
        self._stash_btn.setStyleSheet(_BTN_STYLE)
        self._stash_btn.clicked.connect(self.stash_requested.emit)
        self._stash_btn.setVisible(False)
        header_bar.addWidget(self._stash_btn)

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

    def reload(self, extra_tips: list[str] | None = None, limit: int = PAGE_SIZE) -> None:
        if self._loading:
            return
        self._loading = True
        self._extra_tips = extra_tips
        self._reload_limit = limit
        queries = self._queries

        signals = _LoadSignals()
        signals.reload_done.connect(self._on_reload_done)
        self._load_signals = signals  # prevent GC

        def _worker():
            commits = queries.get_commit_graph.execute(limit=limit, extra_tips=extra_tips)
            branches = queries.get_branches.execute()
            dirty = queries.is_dirty.execute()
            head_oid = queries.get_head_oid.execute() or ""
            signals.reload_done.emit(commits, branches, dirty, head_oid)

        threading.Thread(target=_worker, daemon=True).start()

    def reload_with_extra_tip(self, oid: str) -> None:
        """Reload graph including the given oid as an extra walker tip, then scroll to it."""
        # If oid is already in the current commit list, just scroll and select
        for row in range(self._model.rowCount()):
            row_oid = self._model.data(self._model.index(row, 0), Qt.UserRole)
            if row_oid == oid:
                self.scroll_to_oid(oid, select=True)
                return
        # Otherwise reload with extra tip and scroll after load
        self._pending_scroll_oid = oid
        self.reload(extra_tips=[oid])

    def _on_reload_done(self, commits: list[Commit], branches: list[Branch],
                        is_dirty: bool, head_oid: str) -> None:
        self._loading = False
        self._stash_btn.setVisible(is_dirty)
        if self._queries is None:
            return

        self._loaded_count = len(commits)
        self._has_more = len(commits) == self._reload_limit

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
                parents=[head_oid] if head_oid else [],
            )
            all_commits.insert(0, synthetic)

        self._model.reload(all_commits, refs, head_branch)
        self._update_column_widths()

        if self._pending_scroll_oid:
            # Check if the target oid was found in loaded commits
            found = any(
                self._model.data(self._model.index(r, 0), Qt.UserRole) == self._pending_scroll_oid
                for r in range(self._model.rowCount())
            )
            if found:
                self.scroll_to_oid(self._pending_scroll_oid, select=True)
                self._pending_scroll_oid = None
            elif self._has_more:
                # Target not found yet — retry with double the limit
                oid = self._pending_scroll_oid
                tips = self._extra_tips
                new_limit = self._reload_limit * 2
                self._pending_scroll_oid = oid
                self._loading = False
                self.reload(extra_tips=tips, limit=new_limit)
            else:
                # No more commits to load — give up
                self._pending_scroll_oid = None

    def _get_visible_rows(self) -> tuple[int, int]:
        """Return (first_visible_row, last_visible_row) indices."""
        vp = self._view.viewport()
        first = self._view.rowAt(0)
        last = self._view.rowAt(vp.height())
        if first < 0:
            first = 0
        if last < 0:
            last = self._model.rowCount() - 1
        return first, last

    _INFO_MIN_W = 250

    def _compute_info_width(self, first: int, last: int) -> int:
        """Compute the minimum info column width to fit visible rows' content."""
        fm = self._view.fontMetrics()
        spacing = fm.horizontalAdvance("  ")
        pad = CELL_PAD * 2
        max_w = self._INFO_MIN_W
        for r in range(first, last + 1):
            info = self._model.data(self._model.index(r, 1), Qt.UserRole + 1)
            if info is None:
                continue
            author = info.author.split("<")[0].strip() if "<" in info.author else info.author
            w1 = fm.horizontalAdvance(author) + fm.horizontalAdvance(info.timestamp) + spacing
            badges_w = sum(
                fm.horizontalAdvance(n) + BADGE_H_PAD * 2 + BADGE_GAP
                for n in info.branch_names
            )
            w2 = badges_w + fm.horizontalAdvance(info.short_oid) + spacing
            max_w = max(max_w, w1, w2)
        return max_w + pad

    def _update_column_widths(self) -> None:
        if self._model.rowCount() == 0:
            return
        first, last = self._get_visible_rows()

        max_lanes = max(
            (self._model.data(self._model.index(r, 0), Qt.UserRole + 1).n_lanes
             for r in range(first, last + 1)
             if self._model.data(self._model.index(r, 0), Qt.UserRole + 1) is not None),
            default=1,
        )
        graph_w = max_lanes * LANE_W + LANE_W
        info_w = self._compute_info_width(first, last)
        self._view.setColumnWidth(0, graph_w)
        # Info column stretches to fill, but set minimumWidth so
        # the splitter gives us enough total space
        self.setMinimumWidth(graph_w + info_w)

    def _on_scroll(self, value: int) -> None:
        self._update_column_widths()
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
            more = queries.get_commit_graph.execute(limit=PAGE_SIZE, skip=skip, extra_tips=self._extra_tips)
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

    def scroll_to_oid(self, oid: str, select: bool = False) -> None:
        """Scroll so the row with the given oid is the first visible item."""
        for row in range(self._model.rowCount()):
            row_oid = self._model.data(self._model.index(row, 0), Qt.UserRole)
            if row_oid == oid:
                index = self._model.index(row, 0)
                self._view.scrollTo(index, QTableView.PositionAtTop)
                if select:
                    self._view.setCurrentIndex(index)
                return

    def clear_selection(self) -> None:
        self._view.clearSelection()
        self._view.setCurrentIndex(self._model.index(-1, 0))

    def set_stash_visible(self, visible: bool) -> None:
        self._stash_btn.setVisible(visible)

    def _on_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        oid = self._model.data(self._model.index(current.row(), 0), Qt.UserRole)
        if oid:
            self.commit_selected.emit(oid)
