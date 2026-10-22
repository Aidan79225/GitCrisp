from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QObject, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from git_gui.domain.entities import (
    WORKING_TREE_OID,
    Branch,
    Commit,
    RepoState,
    ResetMode,
    Tag,
    split_remote_branch,
)
from git_gui.domain.ports import IRepoStore
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.graph_model import INFO_ROLE, OID_ROLE, GraphModel
from git_gui.presentation.theme import ColorRole, connect_widget, get_theme_manager
from git_gui.presentation.widgets.commit_row_delegate import CommitRowDelegate
from git_gui.resources import get_resource_path

PAGE_SIZE = 50
MAX_RELOAD_LIMIT = 2000  # cap doubling retry to avoid unbounded loads

_REMOTES_UNKNOWN = (
    "The remotes did not load, so which one holds this branch is unknown. "
    "Fix the remote configuration (git remote -v), then try again."
)


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
            colors = get_theme_manager().current.colors
            painter.fillRect(row_rect, colors.as_qcolor(ColorRole.HOVER_OVERLAY))
            painter.end()
        super().paintEvent(event)


logger = logging.getLogger(__name__)


class _LoadSignals(QObject):
    # commits, branches, tags, is_dirty, head_oid, repo_state, merge_head,
    # first_parent, path_filter, generation
    reload_done = Signal(list, list, list, bool, str, object, object, bool, object, int)
    # more, first_parent, path_filter, generation
    append_done = Signal(list, bool, object, int)
    # generation, error message — the worker raised instead of producing a result
    load_failed = Signal(int, str)


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


def _ref_labels(
    branches: list[Branch], tags: list[Tag], head_oid: str
) -> tuple[dict[str, list[str]], str | None]:
    """The badge labels for each commit, and the checked-out local branch.

    HEAD gets a badge of its own only when detached, when no local branch is.
    """
    refs: dict[str, list[str]] = {}
    head_branch: str | None = None
    for b in branches:
        refs.setdefault(b.target_oid, []).append(b.name)
        if b.is_head and not b.is_remote:
            head_branch = b.name
    for t in tags:
        refs.setdefault(t.target_oid, []).append(f"tag:{t.name}")
    if head_oid and not head_branch:
        refs.setdefault(head_oid, []).insert(0, "HEAD")
    return refs, head_branch


_WORKING_TREE_MESSAGES = {
    RepoState.MERGING: "Merge in progress (conflicts)",
    RepoState.REBASING: "Rebase in progress",
}


def _working_tree_row(
    state: RepoState, head_oid: str, merge_head: str | None, commits: list[Commit]
) -> Commit:
    """The synthetic row for uncommitted changes, drawn on top of HEAD."""
    parents = [head_oid] if head_oid else []
    # The walk does not push MERGE_HEAD. A parent that never arrives as a
    # row would hold its lane open to the bottom.
    if state is RepoState.MERGING and merge_head and any(c.oid == merge_head for c in commits):
        parents.append(merge_head)
    return Commit(
        oid=WORKING_TREE_OID,
        message=_WORKING_TREE_MESSAGES.get(state, "Uncommitted Changes"),
        author="",
        timestamp=datetime.now(),
        parents=parents,
    )


def _add_one_or_submenu(
    menu: QMenu, title: str, labels: list[str], single_label: Callable[[str], str]
) -> list[QAction]:
    """Add an action per label: a lone one to `menu` itself, labelled
    `single_label(label)`; several to a `title` submenu. Returns them in order."""
    if not labels:
        return []
    if len(labels) == 1:
        return [menu.addAction(single_label(labels[0]))]
    sub = menu.addMenu(title)
    sub.setToolTipsVisible(True)
    return [sub.addAction(label) for label in labels]


def _add_branch_actions(
    menu: QMenu, title: str, names: list[str], emit: Callable[[str], None]
) -> None:
    """Add a '<title>: <name>' action, or a `title` submenu of names, each emitting its name."""
    actions = _add_one_or_submenu(menu, title, names, lambda name: f"{title}: {name}")
    for action, name in zip(actions, names, strict=True):
        action.triggered.connect(lambda _checked=False, n=name: emit(n))


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

        # The glyph buttons below would otherwise be announced by screen
        # readers as "black up-pointing triangle" and the like.
        self._input.setAccessibleName("Search commits")

        btn_prev = QPushButton("▲")
        btn_prev.setAccessibleName("Previous match")
        btn_prev.setFixedSize(28, 28)
        btn_prev.setToolTip("Previous match (Shift+Enter)")
        btn_prev.clicked.connect(lambda: self.navigate_requested.emit(-1))
        layout.addWidget(btn_prev)

        btn_next = QPushButton("▼")
        btn_next.setAccessibleName("Next match")
        btn_next.setFixedSize(28, 28)
        btn_next.setToolTip("Next match (Enter)")
        btn_next.clicked.connect(lambda: self.navigate_requested.emit(1))
        layout.addWidget(btn_next)

        btn_close = QPushButton("✕")
        btn_close.setAccessibleName("Close search")
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


class _ElidedLabel(QLabel):
    """A one-line label that shortens its text to the width it is given.

    A plain QLabel's minimum width is its whole text, so a long file path
    became the commit list's minimum width and squeezed the diff pane.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setAccessibleName(text)
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = self.contentsRect().width()
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.ElideMiddle, width))


class _PathFilterBar(QWidget):
    """Chip showing the path the commit list is currently filtered to."""

    closed = Signal()
    follow_toggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._label = _ElidedLabel()
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._label, 1)

        self._follow = QCheckBox("Follow renames")
        self._follow.setChecked(True)
        self._follow.setToolTip(
            "Keep following the file's history past a rename, back to its earlier name."
        )
        self._follow.toggled.connect(self.follow_toggled)
        layout.addWidget(self._follow)

        btn_close = QPushButton("✕")
        btn_close.setAccessibleName("Clear file filter")
        btn_close.setFixedSize(28, 28)
        btn_close.setToolTip("Show the full history again")
        btn_close.clicked.connect(self.closed.emit)
        layout.addWidget(btn_close)

    def open(self, path: str) -> None:
        self._label.set_full_text(f"History of  {path}")
        self._label.setToolTip(path)
        self.setVisible(True)

    def close_bar(self) -> None:
        self.setVisible(False)

    def follow(self) -> bool:
        return self._follow.isChecked()


class GraphWidget(QWidget):
    commit_selected = Signal(str)  # emits oid (or WORKING_TREE_OID)
    path_filter_changed = Signal(object)  # str path, or None when cleared
    commit_double_clicked = Signal(str)  # oid — double-click to switch branch
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
    reflog_requested = Signal()
    load_failed = Signal(str)  # why the commits could not be loaded
    setting_save_failed = Signal(str)  # why the first-parent choice could not be saved

    def __init__(
        self, queries: QueryBus, commands: CommandBus, repo_store: IRepoStore, parent=None
    ) -> None:
        super().__init__(parent)
        self._queries = queries
        self._loaded_count = 0  # how many commits loaded (excluding synthetic)
        self._has_more = True
        self._loading = False
        # Set when reload() is called while a load is in flight. That load
        # was asked for earlier, so its result is discarded and loaded again.
        self._reload_queued = False
        # Bumped on every repo switch. A load hands its generation back with
        # its result, so one that finishes after the switch is recognised as
        # the previous repo's and dropped.
        self._load_generation = 0
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
        # Path the commit list is filtered to (file history), or None for the
        # full graph. Filtered listings are a sparse subset of history, so the
        # lane graph is suppressed while one is active.
        self._path_filter: str | None = None

        self._view = _GraphTableView()
        self._view.setAccessibleName("Commit history")
        self._view.setSelectionBehavior(QTableView.SelectRows)
        self._view.setSelectionMode(QTableView.SingleSelection)
        self._view.setShowGrid(False)
        self._view.verticalHeader().setVisible(False)
        self._view.setEditTriggers(QTableView.NoEditTriggers)

        # Hide column header — "Graph" / "Info" labels add no value
        self._view.horizontalHeader().setVisible(False)

        # Let delegates control row height via sizeHint
        self._view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        # One delegate paints the whole row: lane graph first, then the commit
        # info indented just past that row's own lanes.
        self._view.setItemDelegate(CommitRowDelegate(self._view))

        self._model = GraphModel([], {})
        self._view.setModel(self._model)

        # Single column, stretched to fill the panel
        self._view.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.selectionModel().currentRowChanged.connect(self._on_row_changed)
        self._view.doubleClicked.connect(self._on_double_clicked)

        self._view.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._show_context_menu)

        # Header bar with action buttons
        header_bar = QHBoxLayout()
        header_bar.setContentsMargins(4, 4, 4, 4)
        self._styled_buttons: list[QPushButton] = []
        self._tinted_button_icons: list[tuple[QPushButton, str]] = []
        # Icon-only buttons: the tooltip is only a screen reader's
        # description, so each also gets a short accessible name.
        for icon_name, name, tooltip, signal in [
            ("ic_reload", "Reload", "Reload (F5)", self.reload_requested),
            ("ic_push", "Push", "Push", self.push_requested),
            ("ic_pull", "Pull", "Pull", self.pull_requested),
            ("ic_fetch", "Fetch all", "Fetch All --prune", self.fetch_all_requested),
            ("ic_insight", "Git Insight", "Git Insight", self.insight_requested),
            (
                "ic_reflog",
                "Reflog",
                "Reflog — where HEAD has been, and how to get back there",
                self.reflog_requested,
            ),
        ]:
            btn = QPushButton()
            btn.setAccessibleName(name)
            btn.setFixedSize(QSize(36, 36))
            btn.setIconSize(QSize(28, 28))
            btn.setToolTip(tooltip)
            btn.clicked.connect(signal.emit)
            header_bar.addWidget(btn)
            self._styled_buttons.append(btn)
            self._tinted_button_icons.append((btn, icon_name))

        self._first_parent_btn = QPushButton()
        self._first_parent_btn.setAccessibleName("First-parent history")
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
        self._stash_btn.setAccessibleName("Stash")
        self._stash_btn.setFixedSize(QSize(36, 36))
        self._stash_btn.setIconSize(QSize(28, 28))
        self._tinted_button_icons.append((self._stash_btn, "ic_stash"))
        self._stash_btn.setToolTip("Stash")
        self._stash_btn.clicked.connect(self.stash_requested.emit)
        self._stash_btn.setVisible(False)
        header_bar.addWidget(self._stash_btn)
        self._styled_buttons.append(self._stash_btn)

        # Path filter chip (hidden by default, shown by set_path_filter)
        self._path_filter_bar = _PathFilterBar()
        self._path_filter_bar.closed.connect(self.clear_path_filter)
        self._path_filter_bar.follow_toggled.connect(self._on_follow_toggled)

        # Search bar (hidden by default, toggled by Ctrl+F)
        self._search_bar = _SearchBar()
        # Oids of the matching commits, not rows: a reload shifts the rows
        # (the working-tree row comes and goes, a fetch adds commits).
        self._search_matches: list[str] = []
        self._search_idx = -1  # current position in _search_matches
        self._pending_search: str | None = None  # search to re-run after full reload
        # The reload limit a search's full-history load replaced, put back
        # when the search closes; None while no search has widened it.
        self._limit_before_search: int | None = None
        self._search_bar.input_widget.textChanged.connect(self._on_search_text_changed)
        self._search_bar.navigate_requested.connect(self._on_search_navigate)
        self._search_bar.closed.connect(self._close_search)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header_bar)
        layout.addWidget(self._path_filter_bar)
        layout.addWidget(self._search_bar)
        layout.addWidget(self._view)

        self._rebuild_styles()
        connect_widget(self, rebuild=self._rebuild_styles)

    def _rebuild_styles(self) -> None:
        style = _btn_style()
        for btn in self._styled_buttons:
            btn.setStyleSheet(style)
        on_bg = get_theme_manager().current.colors.as_qcolor(ColorRole.ON_BACKGROUND)
        for btn, icon_name in self._tinted_button_icons:
            btn.setIcon(_tinted_icon(str(_ARTS / f"{icon_name}.svg"), on_bg))

    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        # Whatever the previous repo still has in flight is no longer wanted,
        # and may never answer at all: a repo deleted from under us fails its
        # load. Waiting on it kept the new repo from loading.
        self._load_generation += 1
        self._loading = False
        self._reload_queued = False
        # The previous repo's selection and file history mean nothing here.
        self._selected_oid = None
        if self._path_filter is not None:
            self._leave_path_filter()
        else:
            self._reset_paging()
        # The previous repo's commits mean nothing here, and would stay on
        # screen under this repo's name if its first load failed.
        self._model.reload([], {})
        self._load_new_listing()

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
            self._remember_first_parent(self._repo_path, checked)
        # No-op if queries aren't wired up yet (empty state).
        if self._queries is not None:
            self.reload()

    def _remember_first_parent(self, path: str, checked: bool) -> None:
        """Persist the choice, reporting a failed write rather than raising.

        The in-memory store already holds it. An OSError escaping the slot (a
        file locked by antivirus, a full disk) would skip the reload, leaving
        the button pressed over a graph drawn in the other mode.
        """
        self._repo_store.set_repo_setting(path, "first_parent", checked)
        try:
            self._repo_store.save()
        except OSError as e:
            logger.warning("Could not save the first-parent setting: %s", e)
            self.setting_save_failed.emit(str(e))

    def set_path_filter(self, path: str) -> None:
        """Show only the commits that touched `path` (file history)."""
        if self._path_filter == path and self._path_filter_bar.isVisible():
            return
        self._path_filter = path
        self._path_filter_bar.open(path)
        self._reset_paging()
        self.path_filter_changed.emit(path)
        self._load_new_listing()

    def clear_path_filter(self) -> None:
        if self._path_filter is None:
            return
        self._leave_path_filter()
        self._load_new_listing()

    def _leave_path_filter(self) -> None:
        self._path_filter = None
        self._path_filter_bar.close_bar()
        self._reset_paging()
        self.path_filter_changed.emit(None)

    def _reset_paging(self) -> None:
        """Drop paging, scroll and search-load state that belongs to the previous listing.

        A limit doubled for the previous one (up to 2000 for a deep
        divergence) would otherwise over-load the next one's first render.
        A search left waiting on the previous listing's full load would run
        over the next one's first page and report that as all its matches.
        """
        self._reload_limit = PAGE_SIZE
        self._limit_before_search = None
        self._pending_search = None
        self._extra_tips = None
        self._pending_scroll_oid = None
        self._pending_merge_base = None
        self._scroll_anchor_oid = None
        self._has_more = True

    def _on_follow_toggled(self, _checked: bool) -> None:
        if self._path_filter is not None:
            self._reset_paging()
            self._load_new_listing()

    def _load_new_listing(self) -> None:
        """Load the listing that replaced the previous one, and search it if a search is open.

        The previous listing's matches say nothing about this one, so an open
        search runs again, loading the whole of it as typing does.
        """
        needle = self._search_bar.text()
        if needle.strip():
            self._on_search_text_changed(needle)
        else:
            self.reload()

    def reload(self, extra_tips: list[str] | None = None, limit: int | None = None) -> None:
        # Sticky semantic: a bare reload() preserves both the user's last-
        # clicked diverged branch (extra_tips) and the load size that was
        # needed to draw its lane (limit). Auto-reloads from the change
        # detector and post-operation flows pass neither, and would otherwise
        # regress to PAGE_SIZE — losing the merge base from the loaded set
        # and reverting the diverged lane to a floating circle.
        # set_buses() explicitly clears state on repo switch.
        if self._queries is None:
            return  # no repo open: a load could only fail
        if extra_tips is not None:
            self._extra_tips = extra_tips
        if limit is not None:
            self._reload_limit = limit
        if self._loading:
            self._reload_queued = True
            return
        self._loading = True
        self._capture_scroll_anchor()
        effective_tips = self._extra_tips
        effective_limit = self._reload_limit
        queries = self._queries
        fp = self._first_parent
        path = self._path_filter
        follow = self._path_filter_bar.follow()

        signals = _LoadSignals()
        signals.reload_done.connect(self._on_reload_done)
        signals.load_failed.connect(self._on_load_failed)
        self._load_signals = signals  # prevent GC
        generation = self._load_generation

        # Pinning an out-of-page tip draws it with no descendants — a merged
        # branch rendered as a lane that never merges. So ask for it only once
        # the doubling retry has nowhere deeper to go, where a pinned row beats
        # a click that appears to do nothing.
        pin = effective_limit >= MAX_RELOAD_LIMIT

        def _worker():
            try:
                if path is None:
                    commits = queries.get_commit_graph.execute(
                        limit=effective_limit,
                        extra_tips=effective_tips,
                        first_parent=fp,
                        pin_unreachable=pin,
                    )
                else:
                    commits = queries.get_file_history.execute(
                        path, limit=effective_limit, follow=follow
                    )
                branches = queries.get_branches.execute()
                tags = queries.get_tags.execute()
                dirty = queries.is_dirty.execute()
                head_oid = queries.get_head_oid.execute() or ""
                repo_state = queries.get_repo_state.execute()
                merge_head = queries.get_merge_head.execute()
            except Exception as e:
                logger.warning("Graph reload failed: %s", e)
                signals.load_failed.emit(generation, str(e))
                return
            signals.reload_done.emit(
                commits,
                branches,
                tags,
                dirty,
                head_oid,
                repo_state,
                merge_head,
                fp,
                path,
                generation,
            )

        threading.Thread(target=_worker, daemon=True).start()

    def reload_with_extra_tip(self, oid: str, extra_tips: list[str] | None = None) -> None:
        """Reload graph including the given oid as an extra walker tip, then
        scroll to it and select it (highlighting the branch's tip row and
        loading its commit into the diff pane). For diverged tips, also load
        down to the merge base with HEAD so the lane converges into HEAD's
        mainline visually.

        `extra_tips` are pushed alongside `oid` but not scrolled to — a
        clicked local branch passes its upstream here, so a branch that is
        behind still draws the commits its remote is holding ahead of it
        instead of ending at a tip with nothing above it.
        """
        tips = [oid, *(t for t in extra_tips or [] if t != oid)]
        if self._path_filter is not None:
            self._select_in_file_history(oid, tips)
            return

        # Nothing to fetch when every tip is already drawn — just scroll and select.
        if self._loaded_oids().issuperset(tips):
            self.scroll_to_oid(oid, select=True)
            return
        self._load_tips_and_land(oid, tips)

    def _select_in_file_history(self, oid: str, tips: list[str]) -> None:
        """Select `oid` in the file history, paging further in to find it.

        File history lists only HEAD's commits that touched the file, so a
        branch tip may never be among them. One that cannot be goes to the
        full graph, which can load it, at once. Any other goes there only
        once the history has run out without it: leaving earlier threw away
        the file view for a commit on a later page.
        """
        if self._row_of(oid) is not None:
            self.scroll_to_oid(oid, select=True)
        elif self._has_more and self._may_be_in_file_history(oid):
            self._pending_scroll_oid = oid
            self._pending_merge_base = None
            self.reload(extra_tips=tips)
        else:
            self._show_in_full_graph(oid, tips)

    def _may_be_in_file_history(self, oid: str) -> bool:
        """Whether `oid` is a commit HEAD reaches that changed the filtered file.

        No other commit is in the file history, and paging in to find that
        out walked the file's whole history, the list jumping to its top at
        each step. A commit from before a followed rename changed the file
        under its old name, so it is shown in the full graph as well. When
        the answer cannot be read, the history is paged in as before.

        A followed history lists no merge at all, while a merge's changed
        files come from its first parent alone: one that brought in a side
        branch's change to the file names it. Without follow, git does list
        a merge whose file differs from every parent; the first-parent diff
        cannot tell that one from the rest, so there a merge is paged in for.
        """
        queries = self._queries
        try:
            head_oid = queries.get_head_oid.execute()
            if not head_oid:
                return False  # an unborn branch has no history
            # is_ancestor is False for HEAD itself, where the history starts.
            if oid != head_oid and not queries.is_ancestor.execute(oid, head_oid):
                return False
            if self._path_filter_bar.follow() and self._is_merge(oid):
                return False
            changed = queries.get_commit_files.execute(oid)
        except Exception as e:
            logger.warning("Could not tell whether %s is in the file history: %s", oid[:8], e)
            return True
        return any(f.path == self._path_filter for f in changed)

    def _is_merge(self, oid: str) -> bool:
        return len(self._queries.get_commit_detail.execute(oid).parents) > 1

    def _show_in_full_graph(self, oid: str, tips: list[str]) -> None:
        self._leave_path_filter()
        self._load_tips_and_land(oid, tips)

    def _load_tips_and_land(self, oid: str, tips: list[str]) -> None:
        """Load the full graph with `tips` pushed, then scroll to and select `oid`."""
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
        self.reload(extra_tips=tips)

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
        path_filter: str | None = None,
        generation: int | None = None,
    ) -> None:
        if generation is not None and generation != self._load_generation:
            return  # the previous repo's load, finishing after a switch
        self._loading = False
        self._stash_btn.setVisible(is_dirty)
        if self._queries is None:
            return

        if self._reload_if_stale(first_parent, path_filter):
            return

        self._count_page(commits)
        refs, head_branch = _ref_labels(branches, tags, head_oid)
        rows = list(commits)
        # The synthetic "Uncommitted Changes" row is anchored to HEAD's parents,
        # which say nothing about a path-filtered listing — skip it there.
        if is_dirty and path_filter is None:
            state = repo_state_info.state if repo_state_info else RepoState.CLEAN
            rows.insert(0, _working_tree_row(state, head_oid, merge_head, commits))
        self._model.reload(
            rows,
            refs,
            head_branch,
            first_parent=first_parent,
            show_graph=path_filter is None,
            remote_branches=frozenset(b.name for b in branches if b.is_remote),
        )
        if not self._settle_pending_scroll():
            self._restore_view_state()
        self._run_pending_search()

    def _count_page(self, commits: list[Commit]) -> None:
        """Record how far the walk got and whether it has more.

        A pinned tip rides along past the end of the page, so the page can
        come back longer than the limit. Both of these read the walk, not
        the list: `>=` because a full page still means there is more, and
        the clamp because `skip` counts walker positions — counting the
        pinned row would step over a real commit on the next page.
        """
        self._loaded_count = min(len(commits), self._reload_limit)
        self._has_more = len(commits) >= self._reload_limit

    def _settle_pending_scroll(self) -> bool:
        """Land on the commit a click asked for, or load further to find it.

        Returns whether another load was started; that load, not this one,
        then restores the view.
        """
        target = self._pending_scroll_oid
        if not target:
            return False
        loaded = self._loaded_oids()
        target_loaded = target in loaded
        base_loaded = self._pending_merge_base is None or self._pending_merge_base in loaded
        if target_loaded and base_loaded:
            self._land_on_pending_target()
        elif self._has_more and self._reload_limit < MAX_RELOAD_LIMIT:
            new_limit = min(self._reload_limit * 2, MAX_RELOAD_LIMIT)
            self.reload(extra_tips=self._extra_tips, limit=new_limit)
            return True
        elif self._path_filter is not None and not target_loaded:
            self._show_in_full_graph(target, self._extra_tips or [target])
            return True
        elif target_loaded:
            # The walk ran out, or hit the cap, before the merge base: the
            # converging lane is incomplete, but the target (an old branch
            # tip pinned via extra_tips, say) is still worth landing on.
            self._land_on_pending_target()
        self._pending_scroll_oid = None
        self._pending_merge_base = None
        return False

    def _restore_view_state(self) -> None:
        """Put back the highlight and the scroll position a model reset wiped.

        Without the highlight, the diff pane shows a commit no row is marked
        for; without the scroll, every auto-refresh jumped to the top. A
        selection whose row is gone is forgotten, or a click on that commit
        when it returns would not reach the diff pane.
        """
        selected = self._selected_oid
        if selected is not None and not self._restore_selection_no_scroll(selected):
            self._selected_oid = None
        self._restore_scroll_anchor()

    def _run_pending_search(self) -> None:
        """Run the search that was waiting for the whole history to load."""
        if self._pending_search:
            needle = self._pending_search
            self._pending_search = None
            self._run_search(needle)

    def _reload_if_stale(self, first_parent: bool, path_filter: str | None) -> bool:
        """Load again if the result in hand no longer answers what is wanted.

        It is stale when a reload was asked for while it was in flight (a
        branch click, a post-commit reload, a toggled mode), or when it was
        fetched in a mode that has since changed. Returns whether it was,
        so the caller drops the result instead of drawing it.
        """
        stale = (
            self._reload_queued
            or first_parent != self._first_parent
            or path_filter != self._path_filter
        )
        if stale:
            self._reload_queued = False
            self.reload()
        return stale

    def _on_load_failed(self, generation: int, message: str) -> None:
        """A load raised instead of producing a result.

        The guard needs clearing. Left set, it turns away every reload
        after this one — which is how deleting the repo on screen froze the
        graph, on that repo and on every repo switched to afterwards. A
        reload asked for meanwhile still runs.
        """
        if generation != self._load_generation:
            return
        self._loading = False
        self.load_failed.emit(message)
        if self._reload_queued:
            self._reload_queued = False
            self.reload()

    def _land_on_pending_target(self) -> None:
        """Scroll to and select the commit a click asked for.

        The click decides where the view goes, so the viewport saved before
        the reload is dropped: restoring it would scroll the target away.
        """
        self.scroll_to_oid(self._pending_scroll_oid, select=True)
        self._scroll_anchor_oid = None

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
            self._scroll_anchor_oid = self._oid_at(index.row())
        else:
            self._scroll_anchor_oid = None

    def _restore_scroll_anchor(self) -> None:
        """Scroll the captured anchor OID back to the top of the viewport.
        No-op if the anchor wasn't captured or its commit is no longer
        loaded."""
        if self._scroll_anchor_oid is None:
            return
        row = self._row_of(self._scroll_anchor_oid)
        if row is None:
            self._scroll_anchor_oid = None
            return
        self._view.scrollTo(self._model.index(row, 0), QTableView.PositionAtTop)

    def _restore_selection_no_scroll(self, oid: str) -> bool:
        """Re-apply the highlighted row to the row matching `oid` after a
        model reset, without scrolling. Used in _on_reload_done so the
        graph's highlight survives auto-reloads (RepoChangeDetector,
        post-operation flows) without losing the user's selection.
        Returns whether `oid` still has a row."""
        row = self._row_of(oid)
        if row is None:
            return False
        self._view.selectionModel().setCurrentIndex(
            self._model.index(row, 0),
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        return True

    def _on_scroll(self, value: int) -> None:
        scrollbar = self._view.verticalScrollBar()
        if self._has_more and not self._loading and value >= scrollbar.maximum() - 1:
            self._load_more()

    def _load_more(self) -> None:
        # With no repo open, the emptied list scrolling back to the top reads
        # as reaching the bottom; asking for a page would only report a failure.
        if self._queries is None:
            return
        self._loading = True
        queries = self._queries
        fp = self._first_parent
        skip = self._loaded_count
        path = self._path_filter
        follow = self._path_filter_bar.follow()

        signals = _LoadSignals()
        signals.append_done.connect(self._on_append_done)
        signals.load_failed.connect(self._on_load_failed)
        self._load_signals = signals  # prevent GC
        generation = self._load_generation

        def _worker():
            try:
                if path is None:
                    more = queries.get_commit_graph.execute(
                        limit=PAGE_SIZE, skip=skip, extra_tips=self._extra_tips, first_parent=fp
                    )
                else:
                    more = queries.get_file_history.execute(
                        path, limit=PAGE_SIZE, skip=skip, follow=follow
                    )
            except Exception as e:
                logger.warning("Graph page load failed: %s", e)
                signals.load_failed.emit(generation, str(e))
                return
            signals.append_done.emit(more, fp, path, generation)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_append_done(
        self,
        more: list[Commit],
        first_parent: bool,
        path_filter: str | None = None,
        generation: int | None = None,
    ) -> None:
        if generation is not None and generation != self._load_generation:
            return  # the previous repo's page, finishing after a switch
        self._loading = False
        if self._queries is None:
            return

        if self._reload_if_stale(first_parent, path_filter):
            return

        if not more:
            self._has_more = False
            return

        self._has_more = len(more) >= PAGE_SIZE
        self._loaded_count += min(len(more), PAGE_SIZE)
        # A bare reload loads `_reload_limit` commits. Below what is on screen,
        # it would drop the rows under the user's scroll position and selection.
        self._reload_limit = max(self._reload_limit, self._loaded_count)

        # No refs: the reload labelled every branch and tag tip, loaded or
        # not, along with the detached-HEAD badge that relabelling would drop.
        self._model.append(more, {})

    def _show_context_menu(self, pos) -> None:
        index = self._view.indexAt(pos)
        if not index.isValid():
            return
        oid = self._model.data(self._model.index(index.row(), 0), OID_ROLE)
        if not oid or oid == WORKING_TREE_OID:
            return

        info = self._model.data(self._model.index(index.row(), 0), INFO_ROLE)
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
        # The row's own snapshot tells local from remote: the same load labelled
        # it, and a '/' does not (local branches like "feature/foo" exist).
        remote_set = info.remote_branches if info else frozenset()
        local_branches = [n for n in real_branches if n not in remote_set]
        remote_branches = [n for n in real_branches if n in remote_set]

        if real_branches:
            menu.addSeparator()
        _add_branch_actions(
            menu, "Checkout branch", real_branches, self.checkout_branch_requested.emit
        )
        _add_branch_actions(
            menu,
            "Checkout in New Worktree",
            real_branches,
            self.checkout_in_new_worktree_requested.emit,
        )
        _add_branch_actions(
            menu, "Delete branch", local_branches, self.delete_branch_requested.emit
        )
        self._add_remote_delete_actions(menu, remote_branches)

        self._add_merge_rebase_section(menu, oid, real_branches)

        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _add_remote_delete_actions(self, menu: QMenu, names: list[str]) -> None:
        """Add 'Delete remote branch' for `names`, off for one whose remote is unknown.

        A remote's name may hold a '/', so 'team/upstream/feature' is on
        'team' or on 'team/upstream' depending on which remotes exist. While
        they cannot be listed, only a name with a single '/' has one answer:
        guessing for the others could delete another remote's branch, and
        the confirmation, which joins the parts back together, cannot show it.
        """
        if not names:
            return
        remotes = self._remote_names()
        actions = _add_one_or_submenu(
            menu, "Delete remote branch", names, lambda name: f"Delete remote branch: {name}"
        )
        for action, name in zip(actions, names, strict=True):
            if remotes is None and name.count("/") > 1:
                action.setEnabled(False)
                action.setToolTip(_REMOTES_UNKNOWN)
                continue
            action.triggered.connect(
                lambda _checked=False, n=name, r=remotes or []: self._emit_remote_delete(n, r)
            )

    def _emit_remote_delete(self, name: str, remotes: list[str]) -> None:
        remote, branch = split_remote_branch(name, remotes)
        if remote and branch:
            self.remote_branch_delete_requested.emit(remote, branch)

    def _remote_names(self) -> list[str] | None:
        """The repo's remotes, or None when they cannot be listed.

        One remote with an invalid name or refspec in .git/config fails the
        whole listing. Raising from the menu left the right-click doing nothing.
        """
        try:
            return [r.name for r in self._queries.list_remotes.execute()]
        except Exception as e:
            logger.warning("Listing remotes failed: %s", e)
            return None

    def _add_merge_rebase_section(
        self, menu: QMenu, oid: str, branches_on_commit: list[str]
    ) -> None:
        """Append the Merge / Rebase section to a context menu, applying disable rules."""
        try:
            state_info = self._queries.get_repo_state.execute()
        except Exception:
            return

        head_branch = state_info.head_branch
        state = state_info.state

        # Determine global disable reason (applies to every action)
        global_disable_reason: str | None = None
        if state is RepoState.DETACHED_HEAD:
            global_disable_reason = "HEAD is detached — checkout a branch first"
        elif state is not RepoState.CLEAN:
            global_disable_reason = f"Repository is in {state.name} — resolve or abort first"

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

        def _configure(action: QAction, tooltip: str | None, signal_emit) -> None:
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

        for title, single_label, entries in (
            ("Merge", lambda label: f"Merge {label}", merge_actions),
            ("Rebase", lambda label: f"Rebase {label}", rebase_actions),
            ("Interactive Rebase", lambda label: label, irebase_actions),
        ):
            labels = [label for label, _tooltip, _emit in entries]
            actions = _add_one_or_submenu(menu, title, labels, single_label)
            for action, (_label, tooltip, emit) in zip(actions, entries, strict=True):
                _configure(action, tooltip, emit)

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

    def scroll_to_oid(self, oid: str, select: bool = False) -> None:
        """Scroll so the row with the given oid is the first visible item."""
        row = self._row_of(oid)
        if row is None:
            return
        index = self._model.index(row, 0)
        self._view.scrollTo(index, QTableView.PositionAtTop)
        if select:
            self._view.setCurrentIndex(index)

    def clear_selection(self) -> None:
        self._view.clearSelection()
        self._view.setCurrentIndex(self._model.index(-1, 0))
        # Left set, it would swallow the next click on the same commit.
        self._selected_oid = None

    # ── Search ───────────────────────────────────────────────────────────
    def open_search(self) -> None:
        self._search_bar.open()

    def _close_search(self) -> None:
        self._search_bar.close_bar()
        self._pending_search = None
        self._search_matches.clear()
        self._search_idx = -1
        self._restore_limit_before_search()
        self._view.setFocus()

    def _restore_limit_before_search(self) -> None:
        """Put back the reload limit the search's full-history load replaced.

        Kept, it made every later auto-reload walk and lay out the whole
        history. It never drops below the rows on screen or the selected one,
        and the list is reloaded to that size at once: left holding the whole
        history over a smaller limit, the next auto-reload cut away whatever
        the user had scrolled to or selected. A full load still in flight is
        no longer wanted, so it is replaced the same way.
        """
        if self._limit_before_search is None:
            return
        self._reload_limit = max(self._limit_before_search, self._commits_in_view())
        self._limit_before_search = None
        if self._queries is not None:
            self.reload()

    def _commits_in_view(self) -> int:
        """How many commits a reload needs to keep every row on screen and the selected one."""
        rows = self._model.rowCount()
        if rows == 0:
            return 0
        bottom = self._view.indexAt(self._view.viewport().rect().bottomLeft())
        last_row = bottom.row() if bottom.isValid() else rows - 1
        last_row = max(last_row, self._view.currentIndex().row())
        working_tree_rows = 1 if self._oid_at(0) == WORKING_TREE_OID else 0
        return last_row + 1 - working_tree_rows

    def _on_search_text_changed(self, text: str) -> None:
        needle = text.strip().lower()
        self._search_matches.clear()
        self._search_idx = -1
        if not needle:
            self._pending_search = None
            self._search_bar.set_match_label(0, 0)
            return

        if self._has_more:
            self._search_after_full_load(needle)
            return

        self._run_search(needle)

    def _search_after_full_load(self, needle: str) -> None:
        """Load the whole history, then search it for `needle`.

        Later keystrokes only swap the needle: asking again would discard the
        load already running.
        """
        full_load_running = self._pending_search is not None
        self._pending_search = needle
        if full_load_running:
            return
        if self._limit_before_search is None:
            self._limit_before_search = self._reload_limit
        self.reload(limit=999_999)

    def _run_search(self, needle: str) -> None:
        self._search_matches.clear()
        self._search_idx = -1
        for row in range(self._model.rowCount()):
            index = self._model.index(row, 0)
            info = self._model.data(index, INFO_ROLE)
            if info is None:
                continue
            haystack = f"{info.message}\n{info.author}\n{info.short_oid}\n{info.timestamp}".lower()
            if needle in haystack:
                self._search_matches.append(self._model.data(index, OID_ROLE))
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
        row = self._row_of(self._search_matches[self._search_idx])
        if row is None:
            return  # a reload since the search dropped this commit
        index = self._model.index(row, 0)
        self._view.scrollTo(index, QTableView.PositionAtCenter)
        self._view.setCurrentIndex(index)

    def _row_of(self, oid: str) -> int | None:
        for row in range(self._model.rowCount()):
            if self._oid_at(row) == oid:
                return row
        return None

    def _loaded_oids(self) -> set[str]:
        return {self._oid_at(row) for row in range(self._model.rowCount())}

    def _oid_at(self, row: int) -> str:
        return self._model.data(self._model.index(row, 0), OID_ROLE)

    def _on_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        oid = self._model.data(self._model.index(current.row(), 0), OID_ROLE)
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

    def _on_double_clicked(self, index: QModelIndex) -> None:
        """Double-click a commit to switch to a branch pointing at it.

        The branch-resolution and checkout flow lives in the main window
        (it owns the query/command buses and the confirmation dialogs); here
        we only forward the commit's oid. The synthetic working-tree row has
        no branch to switch to, so it is ignored."""
        if not index.isValid():
            return
        oid = self._model.data(self._model.index(index.row(), 0), OID_ROLE)
        if oid and oid != WORKING_TREE_OID:
            self.commit_double_clicked.emit(oid)
