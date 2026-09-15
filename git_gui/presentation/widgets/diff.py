from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.diff_model import DiffModel
from git_gui.presentation.theme import connect_widget, get_theme_manager
from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle
from git_gui.presentation.widgets.commit_detail import CommitDetailWidget
from git_gui.presentation.widgets.diff_block import (
    make_diff_formats,
    make_file_block,
    make_syntax_formats,
)
from git_gui.presentation.widgets.file_navigator import FileNavigatorWidget
from git_gui.presentation.widgets.hunk_view import add_hunk_view
from git_gui.presentation.widgets.shared_hscroll import SharedHScroll
from git_gui.presentation.widgets.viewport_block_loader import ViewportBlockLoader

logger = logging.getLogger(__name__)


class DiffWidget(QWidget):
    submodule_open_requested = Signal(str)  # emits the submodule path (relative)
    file_history_requested = Signal(str)  # repo-relative path
    blame_requested = Signal(str, object)  # path, revision (None = HEAD)
    commit_oid_copy_requested = Signal(str)  # full 40-char OID — forwarded from _detail
    ref_copy_requested = Signal(str)  # branch/tag name — forwarded from _detail
    merge_abort_requested = Signal()
    rebase_abort_requested = Signal()
    rebase_continue_requested = Signal()
    cherry_pick_abort_requested = Signal()
    revert_abort_requested = Signal()
    cherry_pick_continue_requested = Signal()
    revert_continue_requested = Signal()

    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._current_oid: str | None = None
        # Path the panel is narrowed to while the graph shows a file history.
        self._path_filter: str | None = None
        self._submodule_paths: set[str] = set()

        # Lazy loading — initialized after scroll area is created (see below)
        self._loader: ViewportBlockLoader | None = None

        # ── State banner (merge/rebase in progress) ─────────────────────────
        self._state_banner = QWidget()
        banner_layout = QHBoxLayout(self._state_banner)
        banner_layout.setContentsMargins(8, 6, 8, 6)
        self._banner_label = QLabel("")
        self._banner_label.setStyleSheet("font-weight: bold;")
        self._btn_abort = QPushButton("Abort")
        self._btn_continue = QPushButton("Continue")
        banner_layout.addWidget(self._banner_label, 1)
        banner_layout.addWidget(self._btn_abort)
        banner_layout.addWidget(self._btn_continue)
        self._state_banner.setStyleSheet("background-color: #5c2d2d; border: none; padding: 2px;")
        self._state_banner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._state_banner.setVisible(False)
        self._btn_abort.clicked.connect(self._on_banner_abort)
        self._btn_continue.clicked.connect(self._on_banner_continue)

        # ── Row 1: commit detail (3-line metadata) ──────────────────────────
        self._detail = CommitDetailWidget()
        self._detail.setAutoFillBackground(True)
        self._detail.commit_oid_copy_requested.connect(self.commit_oid_copy_requested.emit)
        self._detail.ref_copy_requested.connect(self.ref_copy_requested.emit)

        # ── Row 2: full commit message ──────────────────────────────────────
        self._msg_view = QPlainTextEdit()
        self._msg_view.setReadOnly(True)
        self._msg_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._msg_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._msg_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._msg_view.viewport().installEventFilter(self)
        self._msg_view.document().setDocumentMargin(12)
        font = self._msg_view.font()
        font.setFamily("Courier New")
        self._msg_view.setFont(font)

        # Wrap the message view in a panel with a slim collapsible header.
        self._msg_panel = QWidget()
        msg_panel_layout = QVBoxLayout(self._msg_panel)
        msg_panel_layout.setContentsMargins(0, 0, 0, 0)
        msg_panel_layout.setSpacing(2)

        msg_header_row = QHBoxLayout()
        msg_header_row.setContentsMargins(0, 0, 0, 0)
        msg_header_row.setSpacing(4)
        self._msg_toggle = _CollapseToggle(expanded=True)
        msg_header_row.addWidget(self._msg_toggle)
        self._msg_header_label = QLabel("Message")
        msg_header_row.addWidget(self._msg_header_label)
        msg_header_row.addStretch()

        msg_panel_layout.addLayout(msg_header_row)
        msg_panel_layout.addWidget(self._msg_view)

        # Cached heights filled in by load_commit; expanded by default.
        self._msg_full_h: int = 0
        self._msg_collapsed_h: int = 0
        self._msg_toggle.state_changed.connect(self._on_msg_toggle)

        # ── Diff container (will live inside the unified scroll area) ────────
        self._diff_container = QWidget()
        self._diff_layout = QVBoxLayout(self._diff_container)
        self._diff_layout.setContentsMargins(0, 4, 0, 4)
        self._diff_layout.setSpacing(8)

        # ── Shared file model + navigator ────────────────────────────────────
        self._diff_model = DiffModel([])
        self._file_navigator = FileNavigatorWidget(self._diff_model)
        self._file_navigator.file_history_requested.connect(self.file_history_requested)
        self._file_navigator.blame_requested.connect(self._request_blame)
        self._file_navigator.currentChanged.connect(self._on_file_selected)
        self._file_navigator.deselected.connect(self._on_file_deselected)

        # ── Unified scroll area ──────────────────────────────────────────────
        self._scroll_content = QWidget()
        scroll_content_layout = QVBoxLayout(self._scroll_content)
        scroll_content_layout.setContentsMargins(0, 0, 0, 0)
        scroll_content_layout.setSpacing(8)
        scroll_content_layout.addWidget(self._detail)
        scroll_content_layout.addWidget(self._msg_panel)
        scroll_content_layout.addWidget(self._file_navigator)
        scroll_content_layout.addWidget(self._diff_container)
        scroll_content_layout.addStretch(1)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QScrollArea.NoFrame)
        self._scroll_area.setWidget(self._scroll_content)

        # Re-point the lazy diff loader at the unified scroll area.
        self._loader = ViewportBlockLoader(self._scroll_area, self._realize_block)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        # One horizontal bar for every hunk, under the pane rather than inside
        # each of them — see SharedHScroll.
        self._hscroll = QScrollBar()
        self._hscroll_sync = SharedHScroll(self._hscroll, self._diff_container, self)

        layout.addWidget(self._state_banner, 0)
        layout.addWidget(self._scroll_area, 1)
        layout.addWidget(self._hscroll, 0)

        # Diff render formats
        self._formats = make_diff_formats()
        self._syntax_formats = make_syntax_formats()

        self._restyle_themed_panels()
        connect_widget(self, rebuild=self._on_theme_changed)

        self._set_empty_state(True)

    def _set_empty_state(self, empty: bool) -> None:
        """Hide or show all sub-panels based on whether a commit is loaded."""
        self._detail.setVisible(not empty)
        self._msg_panel.setVisible(not empty)
        self._file_navigator.setVisible(not empty)
        self._diff_container.setVisible(not empty)
        self._scroll_area.setVisible(not empty)

    def _on_msg_toggle(self, expanded: bool) -> None:
        if self._msg_full_h <= 0 or self._msg_collapsed_h <= 0:
            return
        self._msg_view.setFixedHeight(self._msg_full_h if expanded else self._msg_collapsed_h)

    def update_state_banner(self, state_name: str) -> None:
        """Show or hide the merge/rebase state banner."""
        self._current_state = state_name
        if state_name == "MERGING":
            self._banner_label.setText("\u26a0 Merge in progress")
            self._btn_continue.setVisible(False)
            self._state_banner.setVisible(True)
        elif state_name == "REBASING":
            self._banner_label.setText("\u26a0 Rebase in progress")
            self._btn_continue.setVisible(True)
            self._state_banner.setVisible(True)
        elif state_name == "CHERRY_PICKING":
            self._banner_label.setText("\u26a0 Cherry-pick in progress")
            self._btn_continue.setVisible(True)
            self._state_banner.setVisible(True)
        elif state_name == "REVERTING":
            self._banner_label.setText("\u26a0 Revert in progress")
            self._btn_continue.setVisible(True)
            self._state_banner.setVisible(True)
        else:
            self._state_banner.setVisible(False)

    def _on_banner_abort(self) -> None:
        state = getattr(self, "_current_state", "CLEAN")
        if state == "MERGING":
            self.merge_abort_requested.emit()
        elif state == "REBASING":
            self.rebase_abort_requested.emit()
        elif state == "CHERRY_PICKING":
            self.cherry_pick_abort_requested.emit()
        elif state == "REVERTING":
            self.revert_abort_requested.emit()

    def _on_banner_continue(self) -> None:
        state = getattr(self, "_current_state", "CLEAN")
        if state == "REBASING":
            self.rebase_continue_requested.emit()
        elif state == "CHERRY_PICKING":
            self.cherry_pick_continue_requested.emit()
        elif state == "REVERTING":
            self.revert_continue_requested.emit()

    def _on_theme_changed(self) -> None:
        self._formats = make_diff_formats()
        self._syntax_formats = make_syntax_formats()
        self._restyle_themed_panels()

    def _restyle_themed_panels(self) -> None:
        c = get_theme_manager().current.colors
        outline = c.outline
        bg = c.surface_container_high
        self._detail.setStyleSheet(f"background: {bg};")
        self._msg_view.setStyleSheet(
            f"QPlainTextEdit {{ background: {bg}; "
            f"border: 1px solid {outline}; border-radius: 4px; }}"
        )

    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._current_oid = None
        self._detail.clear()
        self._msg_view.clear()
        self._msg_full_h = 0
        self._msg_collapsed_h = 0
        self._diff_model.reload([])
        self._clear_blocks()
        self._set_empty_state(True)
        self.update_state_banner("CLEAN")

    def eventFilter(self, obj, event):
        # Block mouse selection / drag on the read-only commit message but
        # let wheel events through so they propagate to the outer
        # QScrollArea (the unified scroll). Without this, wheel-scrolling
        # stalls whenever the cursor sits over the message text.
        if obj is self._msg_view.viewport() and event.type() in (
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseMove,
        ):
            return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # A wider pane means less of the content is out of reach.
        self._hscroll_sync.refresh()

    def load_commit(self, oid: str) -> None:
        self._current_oid = oid

        # Fetch commit detail + refs. If the commit no longer exists (e.g. the
        # graph selection points at a rebased/reset commit), clear the panel
        # and bail out instead of crashing.
        try:
            commit = self._queries.get_commit_detail.execute(oid)
        except Exception as e:
            logger.warning("Failed to load commit %r: %s", oid, e)
            self._current_oid = None
            self._detail.clear()
            self._msg_view.clear()
            self._msg_full_h = 0
            self._msg_collapsed_h = 0
            self._diff_model.reload([])
            self._clear_blocks()
            self._set_empty_state(True)
            return
        self._set_empty_state(False)
        branches = self._queries.get_branches.execute()
        refs = [b.name for b in branches if b.target_oid == oid]
        self._detail.set_commit(commit, refs)

        # Full commit message — add trailing newline so last line is always visible
        msg = commit.message
        if not msg.endswith("\n"):
            msg += "\n"
        # Each commit starts with the message expanded — collapse state
        # is per-commit, not per-session.
        self._msg_toggle.blockSignals(True)
        self._msg_toggle.setChecked(True)
        self._msg_toggle.blockSignals(False)
        self._msg_toggle.setArrowType(Qt.DownArrow)

        self._msg_view.setPlainText(msg)
        line_count = msg.count("\n") + 1
        line_h = self._msg_view.fontMetrics().lineSpacing()
        doc_margin = self._msg_view.document().documentMargin() * 2
        self._msg_full_h = int(line_count * line_h + doc_margin)
        self._msg_collapsed_h = int(line_h + doc_margin)
        self._msg_view.setFixedHeight(self._msg_full_h)

        # Files — no auto-selection; show all files' hunks as bordered blocks
        files = self._queries.get_commit_files.execute(oid)
        self._diff_model.reload(self._apply_path_filter(files))
        self._render_all_files(oid)

    def refresh_view(self) -> None:
        """Redraw the current commit after the unified/side-by-side choice changed.

        A full reload rather than a re-layout: the two views build different
        widgets per hunk, so the blocks have to be rebuilt anyway.
        """
        if self._current_oid is not None:
            self.load_commit(self._current_oid)

    def set_path_filter(self, path: str | None) -> None:
        """Restrict the panel to one file, following the graph's file history.

        Passing None restores the full commit view.
        """
        if self._path_filter == path:
            return
        self._path_filter = path
        if self._current_oid is not None:
            self.load_commit(self._current_oid)

    def _apply_path_filter(self, files):
        """Narrow a commit's file list to the filtered path, when it has one.

        A history followed across a rename reaches commits where the file had a
        different name and the filter matches nothing. Showing an empty panel
        there would look broken, so those commits fall back to their full file
        list.
        """
        if self._path_filter is None:
            return files
        matching = [f for f in files if f.path == self._path_filter]
        return matching or files

    # ── Internal helpers ────────────────────────────────────────────────────

    def _sync_hscroll(self) -> None:
        """Re-measure the shared horizontal bar once the layout has settled.

        Deferred: an editor added this turn has no width yet, so its scroll
        range reads as zero until Qt has laid it out.
        """
        QTimer.singleShot(0, self._hscroll_sync.refresh)

    def _clear_blocks(self) -> None:
        """Remove all widgets and items from the diff layout."""
        while self._diff_layout.count():
            item = self._diff_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if self._loader:
            self._loader.clear()
        self._sync_hscroll()

    def _refresh_submodule_paths(self) -> None:
        """Refresh the cached set of submodule paths from the repository."""
        if self._queries is None:
            self._submodule_paths = set()
            return
        try:
            self._submodule_paths = {s.path for s in self._queries.list_submodules.execute()}
        except Exception:
            self._submodule_paths = set()

    def _request_blame(self, path: str) -> None:
        """Blame the file as of the commit on screen, not as of HEAD.

        Asking for blame while reading an old commit means asking what the file
        looked like then; answering with HEAD's blame would be a different
        question.
        """
        self.blame_requested.emit(path, self._current_oid)

    def _show_file_header_menu(self, global_pos, path: str) -> None:
        menu = QMenu(self)
        history_action = menu.addAction("Show file history")
        blame_action = menu.addAction("Blame this file")
        chosen = menu.exec(global_pos)
        if chosen is history_action:
            self.file_history_requested.emit(path)
        elif chosen is blame_action:
            self._request_blame(path)

    def _build_file_block(self, path: str, hunks):
        """Build and return a bordered QFrame containing a file header and per-hunk widgets."""
        is_submodule = path in self._submodule_paths
        on_click = (lambda p=path: self.submodule_open_requested.emit(p)) if is_submodule else None
        frame, inner = make_file_block(
            path,
            on_header_clicked=on_click,
            on_header_context_menu=lambda pos, p=path: self._show_file_header_menu(pos, p),
        )
        frame.setProperty("file_path", path)

        for hunk in hunks:
            add_hunk_view(
                inner,
                hunk,
                self._formats,
                on_header_clicked=on_click,
                syntax_formats=self._syntax_formats,
                filename=path,
            )

        return frame

    def _build_skeleton_block(self, path: str):
        """Build a file block with a skeleton placeholder. Returns (frame, inner, skeleton)."""
        from git_gui.presentation.widgets.diff_block import make_skeleton_container

        is_submodule = path in self._submodule_paths
        on_click = (lambda p=path: self.submodule_open_requested.emit(p)) if is_submodule else None
        frame, inner = make_file_block(
            path,
            on_header_clicked=on_click,
            on_header_context_menu=lambda pos, p=path: self._show_file_header_menu(pos, p),
            on_state_changed=lambda _expanded: self._loader.check_viewport(),
        )
        frame.setProperty("file_path", path)
        skeleton = make_skeleton_container()
        inner.addWidget(skeleton)
        return frame, inner, skeleton

    def _realize_block(self, path: str, inner, skeleton, hunks) -> None:
        """Callback for ViewportBlockLoader — replace skeleton with hunk widgets."""
        if skeleton is not None:
            inner.removeWidget(skeleton)
            skeleton.deleteLater()
        is_submodule = path in self._submodule_paths
        on_click = (lambda p=path: self.submodule_open_requested.emit(p)) if is_submodule else None
        for hunk in hunks:
            add_hunk_view(
                inner,
                hunk,
                self._formats,
                on_header_clicked=on_click,
                syntax_formats=self._syntax_formats,
                filename=path,
            )

        # If the user collapsed this file before realize fired, the newly
        # added hunk widgets default to visible — sync them with the toggle.
        from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle

        frame = inner.parentWidget()  # the QFrame that owns `inner`
        toggle = frame.findChild(_CollapseToggle) if frame is not None else None
        if toggle is not None and not toggle.isChecked():
            for i in range(1, inner.count()):
                item = inner.itemAt(i)
                w = item.widget() if item else None
                if w is not None:
                    w.setVisible(False)
        self._sync_hscroll()

    def _on_file_selected(self, index) -> None:
        if self._current_oid is None:
            return
        if not index.isValid():
            # Selection cleared programmatically — return to all-files view
            self._render_all_files(self._current_oid)
            return
        file_status = self._diff_model.data(index, Qt.UserRole)
        if file_status is None:
            return
        hunks = self._queries.get_file_diff.execute(self._current_oid, file_status.path)
        self._render_single_file(file_status.path, hunks)

    def _on_file_deselected(self) -> None:
        """Return to all-files view when the user click-deselects the current row."""
        if self._current_oid is not None:
            self._render_all_files(self._current_oid)

    def _render_single_file(self, path: str, hunks) -> None:
        """Clear and render one file as a bordered block."""
        self._refresh_submodule_paths()
        self._clear_blocks()
        if self._loader:
            self._loader.clear()
        block = self._build_file_block(path, hunks)
        self._diff_layout.addWidget(block)
        self._diff_layout.addStretch()
        self._sync_hscroll()

    def _render_all_files(self, oid: str) -> None:
        """Render all file blocks as skeletons immediately, then fetch diffs in background."""
        import threading

        from PySide6.QtCore import QObject, Signal

        self._refresh_submodule_paths()
        self._clear_blocks()

        block_refs = []

        row_count = self._diff_model.rowCount()
        for row in range(row_count):
            index = self._diff_model.index(row)
            file_status = self._diff_model.data(index, Qt.UserRole)
            if file_status is None:
                continue
            path = file_status.path
            frame, inner, skeleton = self._build_skeleton_block(path)
            self._diff_layout.addWidget(frame)
            block_refs.append((path, frame, inner, skeleton))

        self._diff_layout.addStretch()

        self._loader.set_blocks(block_refs)

        # Dispatch background fetch
        queries = self._queries

        class _MapSignals(QObject):
            done = Signal(object)  # dict

        signals = _MapSignals()
        signals.done.connect(lambda diff_map: self._loader.set_diff_map(diff_map))
        self._diff_map_signals = signals  # prevent GC

        def _worker():
            try:
                result = queries.get_commit_diff_map.execute(oid)
            except Exception:
                result = {}
            signals.done.emit(result)

        threading.Thread(target=_worker, daemon=True).start()
