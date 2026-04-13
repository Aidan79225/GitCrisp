# git_gui/presentation/widgets/graph.py
from __future__ import annotations
import threading
from datetime import datetime
from git_gui.resources import get_resource_path
from PySide6.QtCore import QModelIndex, QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QStyle,
    QStyleOptionViewItem, QTableView, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import Branch, Commit, Tag, WORKING_TREE_OID
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.theme import get_theme_manager, connect_widget
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
    reload_done = Signal(list, list, list, bool, str, object, object)  # commits, branches, tags, is_dirty, head_oid, repo_state, merge_head
    append_done = Signal(list, list, list)              # more_commits, branches, tags


_ARTS = get_resource_path("arts")


def _tinted_icon(svg_path: str, color: QColor, size: int = 28) -> QIcon:
    src = QIcon(svg_path).pixmap(size, size)
    if src.isNull():
        return QIcon(svg_path)
    tinted = QPixmap(src.size())
    tinted.setDevicePixelRatio(src.devicePixelRatio())
    tinted.fill(Qt.transparent)
    p = QPainter(tinted)
    p.drawPixmap(0, 0, src)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(tinted.rect(), color)
    p.end()
    return QIcon(tinted)


def _btn_style() -> str:
    c = get_theme_manager().current.colors
    return (
        "QPushButton { border: none; border-radius: 4px; }"
        f"QPushButton:hover {{ background-color: {c.hover_overlay}; }}"
    )


class _SearchBar(QWidget):
    """Inline search bar for filtering commits by message, author, hash, or date."""

    navigate_requested = Signal(int)   # +1 = next, -1 = prev
    closed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Search commits — message, author, hash, date …")
        self._input.setClearButtonEnabled(True)
        self._input.returnPressed.connect(lambda: self.navigate_requested.emit(1))
        layout.addWidget(self._input, 1)

        self._label = QLabel()
        self._label.setFixedWidth(60)
        self._label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._label)

        btn_prev = QPushButton("▲")
        btn_prev.setFixedSize(28, 28)
        btn_prev.setToolTip("Previous match (Shift+Enter)")
        btn_prev.clicked.connect(lambda: self.navigate_requested.emit(-1))
        layout.addWidget(btn_prev)

        btn_next = QPushButton("▼")
        btn_next.setFixedSize(28, 28)
        btn_next.setToolTip("Next match (Enter)")
        btn_next.clicked.connect(lambda: self.navigate_requested.emit(1))
        layout.addWidget(btn_next)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(28, 28)
        btn_close.setToolTip("Close (Escape)")
        btn_close.clicked.connect(self.closed.emit)
        layout.addWidget(btn_close)

        # Shift+Enter for previous match
        self._input.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent
        if obj is self._input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.closed.emit()
                return True
            if event.key() == Qt.Key_Return and event.modifiers() & Qt.ShiftModifier:
                self.navigate_requested.emit(-1)
                return True
        return super().eventFilter(obj, event)

    def open(self) -> None:
        self.setVisible(True)
        self._input.setFocus()
        self._input.selectAll()

    def close_bar(self) -> None:
        self.setVisible(False)
        self._input.clear()
        self._label.clear()

    def text(self) -> str:
        return self._input.text()

    def set_match_label(self, current: int, total: int) -> None:
        if total == 0:
            self._label.setText("0 / 0")
        else:
            self._label.setText(f"{current + 1} / {total}")

    @property
    def input_widget(self) -> QLineEdit:
        return self._input


class GraphWidget(QWidget):
    commit_selected = Signal(str)  # emits oid (or WORKING_TREE_OID)
    create_branch_requested = Signal(str)       # oid
    create_tag_requested = Signal(str)          # oid
    checkout_commit_requested = Signal(str)      # oid
    checkout_branch_requested = Signal(str)      # branch name (local or remote)
    delete_branch_requested = Signal(str)        # local branch name
    merge_branch_requested = Signal(str)             # branch name (merge into current)
    merge_commit_requested = Signal(str)             # oid (merge commit into current)
    rebase_onto_branch_requested = Signal(str)       # branch name (rebase current onto)
    rebase_onto_commit_requested = Signal(str)       # oid (rebase current onto commit)
    interactive_rebase_branch_requested = Signal(str)   # branch name
    interactive_rebase_commit_requested = Signal(str)    # oid
    reload_requested = Signal()
    push_requested = Signal()
    pull_requested = Signal()
    fetch_all_requested = Signal()
    stash_requested = Signal()
    insight_requested = Signal()

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
        self._styled_buttons: list[QPushButton] = []
        self._tinted_button_icons: list[tuple[QPushButton, str]] = []
        for icon_name, tooltip, signal in [
            ("ic_reload", "Reload (F5)", self.reload_requested),
            ("ic_push", "Push", self.push_requested),
            ("ic_pull", "Pull", self.pull_requested),
            ("ic_fetch", "Fetch All --prune", self.fetch_all_requested),
            ("ic_insight", "Git Insight", self.insight_requested),
        ]:
            btn = QPushButton()
            btn.setFixedSize(QSize(36, 36))
            btn.setIconSize(QSize(28, 28))
            btn.setToolTip(tooltip)
            btn.clicked.connect(signal.emit)
            header_bar.addWidget(btn)
            self._styled_buttons.append(btn)
            self._tinted_button_icons.append((btn, icon_name))

        header_bar.addStretch()

        self._stash_btn = QPushButton()
        self._stash_btn.setFixedSize(QSize(36, 36))
        self._stash_btn.setIconSize(QSize(28, 28))
        self._tinted_button_icons.append((self._stash_btn, "ic_stash"))
        self._stash_btn.setToolTip("Stash")
        self._stash_btn.clicked.connect(self.stash_requested.emit)
        self._stash_btn.setVisible(False)
        header_bar.addWidget(self._stash_btn)
        self._styled_buttons.append(self._stash_btn)

        # Search bar (hidden by default, toggled by Ctrl+F)
        self._search_bar = _SearchBar()
        self._search_matches: list[int] = []  # row indices of matching commits
        self._search_idx = -1  # current position in _search_matches
        self._pending_search: str | None = None  # search to re-run after full reload
        self._search_bar.input_widget.textChanged.connect(self._on_search_text_changed)
        self._search_bar.navigate_requested.connect(self._on_search_navigate)
        self._search_bar.closed.connect(self._close_search)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header_bar)
        layout.addWidget(self._search_bar)
        layout.addWidget(self._view)

        self._rebuild_styles()
        connect_widget(self, rebuild=self._rebuild_styles)

    def _rebuild_styles(self) -> None:
        style = _btn_style()
        for btn in self._styled_buttons:
            btn.setStyleSheet(style)
        on_bg = get_theme_manager().current.colors.as_qcolor("on_background")
        for btn, icon_name in self._tinted_button_icons:
            btn.setIcon(_tinted_icon(str(_ARTS / f"{icon_name}.svg"), on_bg))


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
            tags = queries.get_tags.execute()
            dirty = queries.is_dirty.execute()
            head_oid = queries.get_head_oid.execute() or ""
            repo_state = queries.get_repo_state.execute()
            merge_head = queries.get_merge_head.execute()
            signals.reload_done.emit(commits, branches, tags, dirty, head_oid, repo_state, merge_head)

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
                        tags: list[Tag], is_dirty: bool, head_oid: str,
                        repo_state_info, merge_head: str | None) -> None:
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
        for t in tags:
            refs.setdefault(t.target_oid, []).append(f"tag:{t.name}")

        # Show HEAD badge only when detached (no local branch is HEAD)
        if head_oid and not head_branch:
            refs.setdefault(head_oid, []).insert(0, "HEAD")

        all_commits = list(commits)
        if is_dirty:
            state_name = repo_state_info.state.name if repo_state_info else "CLEAN"
            if state_name == "MERGING":
                message = "Merge in progress (conflicts)"
                parents = [head_oid, merge_head] if merge_head else [head_oid]
            elif state_name == "REBASING":
                message = "Rebase in progress"
                parents = [head_oid] if head_oid else []
            else:
                message = "Uncommitted Changes"
                parents = [head_oid] if head_oid else []
            parents = [p for p in parents if p]
            synthetic = Commit(
                oid=WORKING_TREE_OID,
                message=message,
                author="",
                timestamp=datetime.now(),
                parents=parents,
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

        # If a search was deferred until all commits were loaded, run it now.
        if self._pending_search:
            needle = self._pending_search
            self._pending_search = None
            self._run_search(needle)

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
            tags = queries.get_tags.execute()
            signals.append_done.emit(more, branches, tags)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_append_done(self, more: list[Commit], branches: list[Branch], tags: list[Tag]) -> None:
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
        for t in tags:
            refs.setdefault(t.target_oid, []).append(f"tag:{t.name}")

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
        menu.setToolTipsVisible(True)
        menu.setStyleSheet(
            "QMenu { padding: 6px; }"
            "QMenu::item { padding: 6px 24px 6px 20px; }"
        )

        menu.addAction("Create Branch").triggered.connect(
            lambda: self.create_branch_requested.emit(oid))
        menu.addAction("Create Tag...").triggered.connect(
            lambda: self.create_tag_requested.emit(oid))
        menu.addAction("Checkout (detached HEAD)").triggered.connect(
            lambda: self.checkout_commit_requested.emit(oid))

        # Filter out HEAD pseudo-ref and tag refs for branch operations
        real_branches = [n for n in branch_names if n != "HEAD" and not n.startswith("tag:")]
        # Distinguish local vs remote branches via the actual branch metadata
        # (the "/" heuristic is wrong: local branches like "feature/foo" exist).
        try:
            all_branches = self._queries.get_branches.execute()
            local_set = {b.name for b in all_branches if not b.is_remote}
        except Exception:
            local_set = set()
        local_branches = [n for n in real_branches if n in local_set]

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

        self._add_merge_rebase_section(menu, oid, real_branches)

        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _add_merge_rebase_section(self, menu: QMenu, oid: str, branches_on_commit: list[str]) -> None:
        """Append the Merge / Rebase section to a context menu, applying disable rules."""
        try:
            state_info = self._queries.get_repo_state.execute()
        except Exception:
            return

        head_branch = state_info.head_branch
        state_name = state_info.state.name

        # Determine global disable reason (applies to every action)
        global_disable_reason: str | None = None
        if state_name == "DETACHED_HEAD":
            global_disable_reason = "HEAD is detached — checkout a branch first"
        elif state_name != "CLEAN":
            global_disable_reason = f"Repository is in {state_name} — resolve or abort first"

        # Compute candidate actions
        branch_targets = [b for b in branches_on_commit if b != head_branch]

        try:
            head_oid = self._queries.get_head_oid.execute()
        except Exception:
            head_oid = None

        show_commit_merge = bool(head_oid) and oid != head_oid
        show_commit_rebase = bool(head_oid) and oid != head_oid

        is_ancestor_of_head = False
        if show_commit_merge and head_oid:
            try:
                is_ancestor_of_head = self._queries.is_ancestor.execute(oid, head_oid)
            except Exception:
                is_ancestor_of_head = False

        if show_commit_merge and is_ancestor_of_head:
            show_commit_merge = False

        # If nothing to show, bail before adding the separator
        if not branch_targets and not show_commit_merge and not show_commit_rebase:
            return

        menu.addSeparator()

        short_oid = oid[:7]
        head_label = head_branch or "HEAD"

        def _add(target_menu: QMenu, label: str, tooltip: str | None, signal_emit) -> None:
            action = target_menu.addAction(label)
            if global_disable_reason:
                action.setEnabled(False)
                action.setToolTip(global_disable_reason)
            elif tooltip:
                action.setEnabled(False)
                action.setToolTip(tooltip)
            else:
                action.triggered.connect(signal_emit)

        # Collect merge actions
        merge_actions: list[tuple[str, str | None, object]] = []
        for b in branch_targets:
            ancestor_tooltip = None
            try:
                if head_oid and self._queries.is_ancestor.execute(oid, head_oid):
                    ancestor_tooltip = "Already up to date"
            except Exception:
                pass
            merge_actions.append((
                f"{b} into {head_label}",
                ancestor_tooltip,
                lambda _checked=False, n=b: self.merge_branch_requested.emit(n),
            ))
        if show_commit_merge:
            merge_actions.append((
                f"commit {short_oid} into {head_label}",
                None,
                lambda _checked=False, o=oid: self.merge_commit_requested.emit(o),
            ))

        # Collect rebase actions
        rebase_actions: list[tuple[str, str | None, object]] = []
        for b in branch_targets:
            rebase_actions.append((
                f"{head_label} onto {b}",
                None,
                lambda _checked=False, n=b: self.rebase_onto_branch_requested.emit(n),
            ))
        if show_commit_rebase:
            rebase_actions.append((
                f"{head_label} onto commit {short_oid}",
                None,
                lambda _checked=False, o=oid: self.rebase_onto_commit_requested.emit(o),
            ))

        # Collect interactive rebase actions
        irebase_actions: list[tuple[str, str | None, object]] = []
        for b in branch_targets:
            irebase_actions.append((
                f"Interactive rebase onto {b}",
                None,
                lambda _checked=False, n=b: self.interactive_rebase_branch_requested.emit(n),
            ))
        if show_commit_rebase:
            irebase_actions.append((
                f"Interactive rebase onto commit {short_oid}",
                None,
                lambda _checked=False, o=oid: self.interactive_rebase_commit_requested.emit(o),
            ))

        # Add merge actions: submenu if ≥2, top-level if 1
        if len(merge_actions) == 1:
            label, tooltip, emit = merge_actions[0]
            _add(menu, f"Merge {label}", tooltip, emit)
        elif merge_actions:
            sub = menu.addMenu("Merge")
            sub.setToolTipsVisible(True)
            for label, tooltip, emit in merge_actions:
                _add(sub, label, tooltip, emit)

        # Add rebase actions: submenu if ≥2, top-level if 1
        if len(rebase_actions) == 1:
            label, tooltip, emit = rebase_actions[0]
            _add(menu, f"Rebase {label}", tooltip, emit)
        elif rebase_actions:
            sub = menu.addMenu("Rebase")
            sub.setToolTipsVisible(True)
            for label, tooltip, emit in rebase_actions:
                _add(sub, label, tooltip, emit)

        # Add interactive rebase actions: submenu if ≥2, top-level if 1
        if len(irebase_actions) == 1:
            label, tooltip, emit = irebase_actions[0]
            _add(menu, label, tooltip, emit)
        elif irebase_actions:
            sub = menu.addMenu("Interactive Rebase")
            sub.setToolTipsVisible(True)
            for label, tooltip, emit in irebase_actions:
                _add(sub, label, tooltip, emit)

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

    # ── Search ───────────────────────────────────────────────────────────
    def open_search(self) -> None:
        """Show the search bar and focus its input."""
        self._search_bar.open()

    def _close_search(self) -> None:
        self._search_bar.close_bar()
        self._search_matches.clear()
        self._search_idx = -1
        self._view.setFocus()

    def _on_search_text_changed(self, text: str) -> None:
        needle = text.strip().lower()
        self._search_matches.clear()
        self._search_idx = -1
        if not needle:
            self._search_bar.set_match_label(0, 0)
            return

        # If not all commits are loaded yet, reload with a large limit so the
        # search covers the full history. The reload callback will re-trigger
        # the search via _run_search_after_load.
        if self._has_more:
            self._pending_search = needle
            self.reload(limit=999_999)
            return

        self._run_search(needle)

    def _run_search(self, needle: str) -> None:
        """Search through all loaded commits for the given needle."""
        self._search_matches.clear()
        self._search_idx = -1
        for row in range(self._model.rowCount()):
            info = self._model.data(self._model.index(row, 1), Qt.UserRole + 1)
            if info is None:
                continue
            haystack = f"{info.message}\n{info.author}\n{info.short_oid}\n{info.timestamp}".lower()
            if needle in haystack:
                self._search_matches.append(row)
        if self._search_matches:
            self._search_idx = 0
            self._jump_to_match()
        self._search_bar.set_match_label(
            self._search_idx, len(self._search_matches),
        )

    def _on_search_navigate(self, direction: int) -> None:
        if not self._search_matches:
            return
        self._search_idx = (self._search_idx + direction) % len(self._search_matches)
        self._jump_to_match()
        self._search_bar.set_match_label(
            self._search_idx, len(self._search_matches),
        )

    def _jump_to_match(self) -> None:
        row = self._search_matches[self._search_idx]
        index = self._model.index(row, 0)
        self._view.scrollTo(index, QTableView.PositionAtCenter)
        self._view.setCurrentIndex(index)

    def _on_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        oid = self._model.data(self._model.index(current.row(), 0), Qt.UserRole)
        if oid:
            self.commit_selected.emit(oid)
