# git_gui/presentation/widgets/graph.py
from __future__ import annotations

import threading
from datetime import datetime

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from git_gui.domain.entities import WORKING_TREE_OID, Branch, Commit, ResetMode, Tag
from git_gui.domain.ports import IRepoStore
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.graph_model import GraphModel
from git_gui.presentation.theme import connect_widget, get_theme_manager
from git_gui.presentation.widgets.commit_info_delegate import CommitInfoDelegate
from git_gui.presentation.widgets.graph_lane_delegate import LANE_W, GraphLaneDelegate
from git_gui.resources import get_resource_path

PAGE_SIZE = 50
MAX_RELOAD_LIMIT = 2000  # cap doubling retry to avoid unbounded loads
_DEFAULT_GRAPH_COL_W = 8 * LANE_W  # 128 px — fits ~8 parallel lanes


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
    # commits, branches, tags, is_dirty, head_oid, repo_state, merge_head, first_parent
    reload_done = Signal(list, list, list, bool, str, object, object, bool)
    # more_commits, branches, tags, first_parent
    append_done = Signal(list, list, list, bool)


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
        f"QPushButton:checked {{ background-color: {c.primary}; }}"
        f"QPushButton:checked:hover {{ background-color: {c.primary}; }}"
    )


class _SearchBar(QWidget):
    """Inline search bar for filtering commits by message, author, hash, or date."""

    navigate_requested = Signal(int)  # +1 = next, -1 = prev
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
    create_branch_requested = Signal(str)  # oid
    create_tag_requested = Signal(str)  # oid
    checkout_commit_requested = Signal(str)  # oid
    checkout_branch_requested = Signal(str)  # branch name (local or remote)
    checkout_in_new_worktree_requested = Signal(str)  # branch name
    delete_branch_requested = Signal(str)  # local branch name
    remote_branch_delete_requested = Signal(str, str)  # (remote, branch)
    merge_branch_requested = Signal(str)  # branch name (merge into current)
    merge_commit_requested = Signal(str)  # oid (merge commit into current)
    rebase_onto_branch_requested = Signal(str)  # branch name (rebase current onto)
    rebase_onto_commit_requested = Signal(str)  # oid (rebase current onto commit)
    interactive_rebase_branch_requested = Signal(str)  # branch name
    interactive_rebase_commit_requested = Signal(str)  # oid
    cherry_pick_requested = Signal(str)  # oid
    revert_commit_requested = Signal(str)  # oid
    reset_to_commit_requested = Signal(str, object)  # oid, ResetMode
    reload_requested = Signal()
    push_requested = Signal()
    pull_requested = Signal()
    fetch_all_requested = Signal()
    stash_requested = Signal()
    insight_requested = Signal()

    def __init__(
        self, queries: QueryBus, commands: CommandBus, repo_store: IRepoStore, parent=None
    ) -> None:
        super().__init__(parent)
        self._queries = queries
        self._loaded_count = 0  # how many commits loaded (excluding synthetic)
        self._has_more = True
        self._loading = False
        self._reload_limit = PAGE_SIZE
        self._pending_scroll_oid: str | None = None
        self._pending_merge_base: str | None = None
        self._extra_tips: list[str] | None = None
        # Tracks the currently-selected commit so the highlight can be
        # restored after a model reset (which clears the view's current row).
        self._selected_oid: str | None = None
        # OID at the top of the viewport before a reload, used to restore
        # the user's scroll position after auto-refresh on focus return.
        self._scroll_anchor_oid: str | None = None

        self._repo_store = repo_store
        self._repo_path: str | None = None
        self._first_parent = False

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
        self._view.setColumnWidth(0, _DEFAULT_GRAPH_COL_W)
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

        # First-parent view toggle (checkable)
        self._first_parent_btn = QPushButton()
        self._first_parent_btn.setFixedSize(QSize(36, 36))
        self._first_parent_btn.setIconSize(QSize(28, 28))
        self._first_parent_btn.setCheckable(True)
        self._first_parent_btn.setToolTip("Show first-parent history only")
        self._first_parent_btn.toggled.connect(self._on_first_parent_toggled)
        header_bar.addWidget(self._first_parent_btn)
        self._styled_buttons.append(self._first_parent_btn)
        self._tinted_button_icons.append((self._first_parent_btn, "ic_first_parent"))

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
        # Reset per-click state — the previous repo's selection is meaningless
        # in the new repo. Reset _reload_limit too so the new repo starts at
        # PAGE_SIZE; otherwise a previously-doubled limit (e.g. 2000 for a
        # deep divergence) carries into the new repo and over-loads on first
        # render.
        self._extra_tips = None
        self._pending_scroll_oid = None
        self._pending_merge_base = None
        self._selected_oid = None
        self._scroll_anchor_oid = None
        self._reload_limit = PAGE_SIZE
        if queries is None:
            self._model.reload([], {})
        else:
            self.reload()

    def set_repo_path(self, path: str | None) -> None:
        """Load the persisted first-parent setting for `path` and sync the
        toggle button silently. Call this BEFORE set_buses on repo switches
        so the first reload reflects the right mode."""
        self._repo_path = path
        if path is None:
            new_value = False
        else:
            new_value = bool(self._repo_store.get_repo_setting(path, "first_parent", False))
        self._first_parent = new_value
        # blockSignals to avoid re-entering the toggle handler.
        was_blocked = self._first_parent_btn.blockSignals(True)
        try:
            self._first_parent_btn.setChecked(new_value)
        finally:
            self._first_parent_btn.blockSignals(was_blocked)

    def _on_first_parent_toggled(self, checked: bool) -> None:
        self._first_parent = checked
        if self._repo_path is not None:
            self._repo_store.set_repo_setting(self._repo_path, "first_parent", checked)
            self._repo_store.save()
        # No-op if queries aren't wired up yet (empty state).
        if self._queries is not None:
            self.reload()

    def reload(self, extra_tips: list[str] | None = None, limit: int | None = None) -> None:
        if self._loading:
            return
        self._loading = True
        self._capture_scroll_anchor()
        # Sticky semantic: a bare reload() preserves both the user's last-
        # clicked diverged branch (extra_tips) and the load size that was
        # needed to draw its lane (limit). Auto-reloads from the change
        # detector and post-operation flows pass neither, and would otherwise
        # regress to PAGE_SIZE — losing the merge base from the loaded set
        # and reverting the diverged lane to a floating circle.
        # set_buses() explicitly clears state on repo switch.
        effective_tips = extra_tips if extra_tips is not None else self._extra_tips
        effective_limit = limit if limit is not None else self._reload_limit
        self._extra_tips = effective_tips
        self._reload_limit = effective_limit
        queries = self._queries
        fp = self._first_parent

        signals = _LoadSignals()
        signals.reload_done.connect(self._on_reload_done)
        self._load_signals = signals  # prevent GC

        def _worker():
            commits = queries.get_commit_graph.execute(
                limit=effective_limit, extra_tips=effective_tips, first_parent=fp
            )
            branches = queries.get_branches.execute()
            tags = queries.get_tags.execute()
            dirty = queries.is_dirty.execute()
            head_oid = queries.get_head_oid.execute() or ""
            repo_state = queries.get_repo_state.execute()
            merge_head = queries.get_merge_head.execute()
            signals.reload_done.emit(
                commits, branches, tags, dirty, head_oid, repo_state, merge_head, fp
            )

        threading.Thread(target=_worker, daemon=True).start()

    def reload_with_extra_tip(self, oid: str) -> None:
        """Reload graph including the given oid as an extra walker tip, then
        scroll to it and select it (highlighting the branch's tip row and
        loading its commit into the diff pane). For diverged tips, also load
        down to the merge base with HEAD so the lane converges into HEAD's
        mainline visually."""
        # If oid is already in the current commit list, just scroll and select
        for row in range(self._model.rowCount()):
            row_oid = self._model.data(self._model.index(row, 0), Qt.UserRole)
            if row_oid == oid:
                self.scroll_to_oid(oid, select=True)
                return

        # Compute merge base with HEAD so the doubling retry knows when to stop.
        merge_base: str | None = None
        if self._queries is not None:
            head_oid = self._queries.get_head_oid.execute() or ""
            if head_oid and head_oid != oid:
                try:
                    merge_base = self._queries.get_merge_base.execute(head_oid, oid)
                except Exception:
                    merge_base = None

        self._pending_scroll_oid = oid
        self._pending_merge_base = merge_base
        self.reload(extra_tips=[oid])

    def _on_reload_done(
        self,
        commits: list[Commit],
        branches: list[Branch],
        tags: list[Tag],
        is_dirty: bool,
        head_oid: str,
        repo_state_info,
        merge_head: str | None,
        first_parent: bool,
    ) -> None:
        self._loading = False
        self._stash_btn.setVisible(is_dirty)
        if self._queries is None:
            return

        # If the user toggled the view mode while this load was in-flight,
        # the in-flight reload() call was dropped by the `if self._loading`
        # guard. Pick up the change now by triggering another reload.
        if first_parent != self._first_parent:
            self.reload()
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

        self._model.reload(all_commits, refs, head_branch, first_parent=first_parent)

        retrying = False
        if self._pending_scroll_oid:
            loaded_oids = {
                self._model.data(self._model.index(r, 0), Qt.UserRole)
                for r in range(self._model.rowCount())
            }
            target_loaded = self._pending_scroll_oid in loaded_oids
            base_loaded = (
                self._pending_merge_base is None or self._pending_merge_base in loaded_oids
            )
            if target_loaded and base_loaded:
                self.scroll_to_oid(self._pending_scroll_oid, select=True)
                self._pending_scroll_oid = None
                self._pending_merge_base = None
            elif self._has_more and self._reload_limit < MAX_RELOAD_LIMIT:
                tips = self._extra_tips
                new_limit = min(self._reload_limit * 2, MAX_RELOAD_LIMIT)
                self._loading = False
                self.reload(extra_tips=tips, limit=new_limit)
                retrying = True
            else:
                # No more commits OR cap reached — the converging lane couldn't
                # be fully loaded. Still scroll+select the target if we managed
                # to load it (e.g. an old branch tip pinned via extra_tips);
                # only give up silently when the target itself is absent.
                if self._pending_scroll_oid in loaded_oids:
                    self.scroll_to_oid(self._pending_scroll_oid, select=True)
                self._pending_scroll_oid = None
                self._pending_merge_base = None

        # Restore the previous selection so the highlighted row stays in sync
        # with the diff pane. The model reset above wiped the view's current
        # row; without this restore the user sees a diff pane with content but
        # no corresponding highlight in the graph. Skipped during retry — the
        # next reload will run this branch.
        if not retrying and self._selected_oid is not None:
            self._restore_selection_no_scroll(self._selected_oid)

        # Restore the user's scroll position. Auto-refreshes (e.g., on focus
        # return) used to silently jump the viewport back to the top because
        # QTableView resets its scrollbar after a model reset. Only kicks in
        # when there's no explicit pending scroll target.
        if not retrying and self._pending_scroll_oid is None:
            self._restore_scroll_anchor()

        # If a search was deferred until all commits were loaded, run it now.
        if self._pending_search:
            needle = self._pending_search
            self._pending_search = None
            self._run_search(needle)

    def _capture_scroll_anchor(self) -> None:
        """Remember the OID of the row at the top of the visible viewport so
        we can restore the scroll position after a reload. Called from
        reload() before the worker runs."""
        if self._model.rowCount() == 0:
            self._scroll_anchor_oid = None
            return
        top_left = self._view.viewport().rect().topLeft()
        index = self._view.indexAt(top_left)
        if index.isValid():
            self._scroll_anchor_oid = self._model.data(
                self._model.index(index.row(), 0), Qt.UserRole
            )
        else:
            self._scroll_anchor_oid = None

    def _restore_scroll_anchor(self) -> None:
        """Scroll the captured anchor OID back to the top of the viewport.
        No-op if the anchor wasn't captured or its commit is no longer
        loaded."""
        if self._scroll_anchor_oid is None:
            return
        for row in range(self._model.rowCount()):
            if self._model.data(self._model.index(row, 0), Qt.UserRole) == self._scroll_anchor_oid:
                index = self._model.index(row, 0)
                self._view.scrollTo(index, QTableView.PositionAtTop)
                return
        # Anchor commit no longer in the loaded set; clear so we don't keep
        # trying.
        self._scroll_anchor_oid = None

    def _restore_selection_no_scroll(self, oid: str) -> None:
        """Re-apply the highlighted row to the row matching `oid` after a
        model reset, without scrolling. Used in _on_reload_done so the
        graph's highlight survives auto-reloads (RepoChangeDetector,
        post-operation flows) without losing the user's selection."""
        for row in range(self._model.rowCount()):
            if self._model.data(self._model.index(row, 0), Qt.UserRole) == oid:
                index = self._model.index(row, 0)
                self._view.selectionModel().setCurrentIndex(
                    index,
                    QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
                )
                return

    def _on_scroll(self, value: int) -> None:
        scrollbar = self._view.verticalScrollBar()
        if self._has_more and not self._loading and value >= scrollbar.maximum() - 1:
            self._load_more()

    def _load_more(self) -> None:
        self._loading = True
        queries = self._queries
        fp = self._first_parent
        skip = self._loaded_count

        signals = _LoadSignals()
        signals.append_done.connect(self._on_append_done)
        self._load_signals = signals  # prevent GC

        def _worker():
            more = queries.get_commit_graph.execute(
                limit=PAGE_SIZE, skip=skip, extra_tips=self._extra_tips, first_parent=fp
            )
            branches = queries.get_branches.execute()
            tags = queries.get_tags.execute()
            signals.append_done.emit(more, branches, tags, fp)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_append_done(
        self, more: list[Commit], branches: list[Branch], tags: list[Tag], first_parent: bool
    ) -> None:
        self._loading = False
        if self._queries is None:
            return

        # User toggled mid-flight: discard the appended page (it was fetched
        # in the wrong mode) and re-run a full reload in the new mode.
        if first_parent != self._first_parent:
            self.reload()
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
        menu.setStyleSheet("QMenu { padding: 6px; }QMenu::item { padding: 6px 24px 6px 20px; }")

        menu.addAction("Create Branch").triggered.connect(
            lambda: self.create_branch_requested.emit(oid)
        )
        menu.addAction("Create Tag...").triggered.connect(
            lambda: self.create_tag_requested.emit(oid)
        )
        menu.addAction("Checkout (detached HEAD)").triggered.connect(
            lambda: self.checkout_commit_requested.emit(oid)
        )

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
                    lambda _checked=False, n=name: self.checkout_branch_requested.emit(n)
                )
            else:
                sub = menu.addMenu("Checkout branch")
                for name in real_branches:
                    sub.addAction(name).triggered.connect(
                        lambda _checked=False, n=name: self.checkout_branch_requested.emit(n)
                    )

        if real_branches:
            if len(real_branches) == 1:
                name = real_branches[0]
                menu.addAction(f"Checkout in New Worktree: {name}").triggered.connect(
                    lambda: self.checkout_in_new_worktree_requested.emit(name)
                )
            else:
                sub = menu.addMenu("Checkout in New Worktree")
                for name in real_branches:
                    sub.addAction(name).triggered.connect(
                        lambda _checked=False, n=name: self.checkout_in_new_worktree_requested.emit(
                            n
                        )
                    )

        if local_branches:
            if len(local_branches) == 1:
                name = local_branches[0]
                menu.addAction(f"Delete branch: {name}").triggered.connect(
                    lambda _checked=False, n=name: self.delete_branch_requested.emit(n)
                )
            else:
                sub = menu.addMenu("Delete branch")
                for name in local_branches:
                    sub.addAction(name).triggered.connect(
                        lambda _checked=False, n=name: self.delete_branch_requested.emit(n)
                    )

        remote_branches = [n for n in real_branches if n not in local_set]
        if remote_branches:
            if len(remote_branches) == 1:
                name = remote_branches[0]
                menu.addAction(f"Delete remote branch: {name}").triggered.connect(
                    lambda _checked=False, n=name: self._emit_remote_delete(n)
                )
            else:
                sub = menu.addMenu("Delete remote branch")
                for name in remote_branches:
                    sub.addAction(name).triggered.connect(
                        lambda _checked=False, n=name: self._emit_remote_delete(n)
                    )

        self._add_merge_rebase_section(menu, oid, real_branches)

        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _emit_remote_delete(self, name: str) -> None:
        """Split a qualified remote-branch name (e.g. 'origin/feature/foo')
        on the first slash and emit (remote, branch). Defensively bail if
        the input is malformed."""
        if "/" not in name:
            return
        remote, branch = name.split("/", 1)
        if not remote or not branch:
            return
        self.remote_branch_delete_requested.emit(remote, branch)

    def _add_merge_rebase_section(
        self, menu: QMenu, oid: str, branches_on_commit: list[str]
    ) -> None:
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
            merge_actions.append(
                (
                    f"{b} into {head_label}",
                    ancestor_tooltip,
                    lambda _checked=False, n=b: self.merge_branch_requested.emit(n),
                )
            )
        if show_commit_merge:
            merge_actions.append(
                (
                    f"commit {short_oid} into {head_label}",
                    None,
                    lambda _checked=False, o=oid: self.merge_commit_requested.emit(o),
                )
            )

        # Collect rebase actions
        rebase_actions: list[tuple[str, str | None, object]] = []
        for b in branch_targets:
            rebase_actions.append(
                (
                    f"{head_label} onto {b}",
                    None,
                    lambda _checked=False, n=b: self.rebase_onto_branch_requested.emit(n),
                )
            )
        if show_commit_rebase:
            rebase_actions.append(
                (
                    f"{head_label} onto commit {short_oid}",
                    None,
                    lambda _checked=False, o=oid: self.rebase_onto_commit_requested.emit(o),
                )
            )

        # Collect interactive rebase actions
        irebase_actions: list[tuple[str, str | None, object]] = []
        for b in branch_targets:
            irebase_actions.append(
                (
                    f"Interactive rebase onto {b}",
                    None,
                    lambda _checked=False, n=b: self.interactive_rebase_branch_requested.emit(n),
                )
            )
        if show_commit_rebase:
            irebase_actions.append(
                (
                    f"Interactive rebase onto commit {short_oid}",
                    None,
                    lambda _checked=False, o=oid: self.interactive_rebase_commit_requested.emit(o),
                )
            )

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

        # ── Cherry-pick / Revert / Reset section ───────────────────────
        # Only show when we have a HEAD and target != HEAD.
        if head_oid and oid != head_oid:
            menu.addSeparator()

            # Cherry-pick
            cp_action = menu.addAction(f"Cherry-pick commit {short_oid}")
            if global_disable_reason:
                cp_action.setEnabled(False)
                cp_action.setToolTip(global_disable_reason)
            else:
                cp_action.triggered.connect(
                    lambda _checked=False, o=oid: self.cherry_pick_requested.emit(o)
                )

            # Revert
            rv_action = menu.addAction(f"Revert commit {short_oid}")
            if global_disable_reason:
                rv_action.setEnabled(False)
                rv_action.setToolTip(global_disable_reason)
            else:
                rv_action.triggered.connect(
                    lambda _checked=False, o=oid: self.revert_commit_requested.emit(o)
                )

            # Reset — only enabled when target is an ancestor of HEAD.
            can_reset = False
            try:
                can_reset = self._queries.is_ancestor.execute(oid, head_oid)
            except Exception:
                can_reset = False

            reset_sub = menu.addMenu(f"Reset {head_label} to {short_oid}")
            reset_sub.setToolTipsVisible(True)
            modes = [
                (ResetMode.SOFT, "Soft (keep index + working tree)"),
                (ResetMode.MIXED, "Mixed (keep working tree, reset index)"),
                (ResetMode.HARD, "Hard (discard everything)"),
            ]
            for mode, label in modes:
                a = reset_sub.addAction(label)
                if global_disable_reason:
                    a.setEnabled(False)
                    a.setToolTip(global_disable_reason)
                elif not can_reset:
                    a.setEnabled(False)
                    a.setToolTip("Target is not an ancestor of HEAD")
                else:
                    a.triggered.connect(
                        lambda _checked=False, o=oid, m=mode: self.reset_to_commit_requested.emit(
                            o, m
                        )
                    )

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
            self._search_idx,
            len(self._search_matches),
        )

    def _on_search_navigate(self, direction: int) -> None:
        if not self._search_matches:
            return
        self._search_idx = (self._search_idx + direction) % len(self._search_matches)
        self._jump_to_match()
        self._search_bar.set_match_label(
            self._search_idx,
            len(self._search_matches),
        )

    def _jump_to_match(self) -> None:
        row = self._search_matches[self._search_idx]
        index = self._model.index(row, 0)
        self._view.scrollTo(index, QTableView.PositionAtCenter)
        self._view.setCurrentIndex(index)

    def _on_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        oid = self._model.data(self._model.index(current.row(), 0), Qt.UserRole)
        # Skip re-emitting for the already-selected commit. A model reset (from
        # an auto-reload) invalidates the current index, so restoring the
        # selection fires currentRowChanged with the same oid. Re-emitting there
        # would reload the diff/commit-detail pane and reset its scroll,
        # yanking the user away from what they were reading. Commits are
        # immutable, so the pane never needs a reload for an unchanged oid; the
        # working tree refreshes via the reload coordinator, not this signal.
        if oid and oid != self._selected_oid:
            self._selected_oid = oid
            self.commit_selected.emit(oid)
