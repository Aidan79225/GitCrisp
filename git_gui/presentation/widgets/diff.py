from __future__ import annotations

import logging
from typing import NamedTuple

from PySide6.QtCore import QEvent, Qt, QTimer, Signal, SignalInstance
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

from git_gui.domain.entities import Branch, Commit, RepoState
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.diff_model import DiffModel
from git_gui.presentation.theme import connect_widget, get_theme_manager
from git_gui.presentation.widgets._collapse_toggle import _CollapseToggle
from git_gui.presentation.widgets.commit_detail import CommitDetailWidget
from git_gui.presentation.widgets.diff_block import (
    make_diff_formats,
    make_file_block,
    make_overflow_notice,
    make_skeleton_container,
    make_syntax_formats,
    use_code_font,
)
from git_gui.presentation.widgets.file_navigator import FileNavigatorWidget
from git_gui.presentation.widgets.hunk_diff import MAX_AGGREGATE_FILE_BLOCKS
from git_gui.presentation.widgets.hunk_view import add_hunk_view, hide_hunks_if_collapsed
from git_gui.presentation.widgets.shared_hscroll import SharedHScroll
from git_gui.presentation.widgets.viewport_block_loader import ViewportBlockLoader

logger = logging.getLogger(__name__)

_MESSAGE_MARGIN = 12


class _OperationBanner(NamedTuple):
    """What the state banner says and does while an operation is in progress."""

    label: str
    abort: SignalInstance
    resume: SignalInstance | None  # None: the operation cannot be continued from here


class _CommitMessageView(QPlainTextEdit):
    """The read-only commit message: as tall as its wrapped text, or one line.

    It wraps at its own width with its scrollbar off, so its height has to come
    from the laid-out lines. Counting the message's newlines instead hid every
    line a long paragraph wrapped onto. The height is measured again whenever
    the width or the font changes.
    """

    def __init__(self) -> None:
        super().__init__()
        self._expanded = True
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(_MESSAGE_MARGIN)
        use_code_font(self)

    def show_message(self, text: str) -> None:
        self.setPlainText(text)
        self._fit_height()

    def set_expanded(self, expanded: bool) -> None:
        """Show the whole message, or only its first line."""
        self._expanded = expanded
        self._fit_height()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)  # re-wraps the text at the new width first
        self._fit_height()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.FontChange:
            self._fit_height()

    def _wrapped_line_count(self) -> int:
        layout = self.document().documentLayout()
        count = 0
        block = self.document().begin()
        while block.isValid():
            layout.ensureBlockLayout(block)
            count += block.layout().lineCount()
            block = block.next()
        return count

    def _fit_height(self) -> None:
        lines = self._wrapped_line_count() if self._expanded else 1
        line_height = self.fontMetrics().lineSpacing()
        self.setFixedHeight(int(lines * line_height + self.document().documentMargin() * 2))


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
        self._current_state = RepoState.CLEAN
        self._banners = self._operation_banners()
        # Bumped whenever the blocks are rebuilt. A diff map fetched for an
        # earlier set of blocks arrives with its generation and is dropped:
        # applied to the new blocks it marked them loaded with no hunks.
        self._blocks_generation = 0

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
        self._msg_view = _CommitMessageView()
        self._msg_view.viewport().installEventFilter(self)

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

        self._msg_toggle.state_changed.connect(self._msg_view.set_expanded)

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

    def _operation_banners(self) -> dict[RepoState, _OperationBanner]:
        return {
            RepoState.MERGING: _OperationBanner(
                "Merge in progress", self.merge_abort_requested, None
            ),
            RepoState.REBASING: _OperationBanner(
                "Rebase in progress", self.rebase_abort_requested, self.rebase_continue_requested
            ),
            RepoState.CHERRY_PICKING: _OperationBanner(
                "Cherry-pick in progress",
                self.cherry_pick_abort_requested,
                self.cherry_pick_continue_requested,
            ),
            RepoState.REVERTING: _OperationBanner(
                "Revert in progress", self.revert_abort_requested, self.revert_continue_requested
            ),
        }

    def update_state_banner(self, state: RepoState) -> None:
        """Show the banner for a merge, rebase, cherry-pick or revert in progress."""
        self._current_state = state
        banner = self._banners.get(state)
        self._state_banner.setVisible(banner is not None)
        if banner is None:
            return
        self._banner_label.setText(f"⚠ {banner.label}")
        self._btn_continue.setVisible(banner.resume is not None)

    def _on_banner_abort(self) -> None:
        banner = self._banners.get(self._current_state)
        if banner is not None:
            banner.abort.emit()

    def _on_banner_continue(self) -> None:
        banner = self._banners.get(self._current_state)
        if banner is not None and banner.resume is not None:
            banner.resume.emit()

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
        # No selector: the label and both buttons take the banner's colours,
        # so the text is set with the background rather than left to a palette
        # that was never chosen to sit on it.
        self._state_banner.setStyleSheet(
            f"background-color: {c.error}; color: {c.on_error}; border: none; padding: 2px;"
        )

    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._clear_commit()
        self.update_state_banner(RepoState.CLEAN)

    def _clear_commit(self) -> None:
        self._current_oid = None
        self._detail.clear()
        self._msg_view.clear()
        self._diff_model.reload([])
        self._clear_blocks()
        self._set_empty_state(True)

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

        # Fetch everything before changing what is on screen. If the commit no
        # longer exists (the graph selection points at a rebased/reset commit)
        # or its files cannot be read (a blob-less partial clone), clear the
        # panel rather than leave this commit's header over the last one's diff.
        try:
            commit = self._queries.get_commit_detail.execute(oid)
            branches = self._queries.get_branches.execute()
            files = self._queries.get_commit_files.execute(oid)
        except Exception as e:
            logger.warning("Failed to load commit %r: %s", oid, e)
            self._clear_commit()
            return
        self._set_empty_state(False)
        self._show_commit_header(oid, commit, branches)

        # Full commit message — add trailing newline so last line is always visible
        msg = commit.message
        if not msg.endswith("\n"):
            msg += "\n"
        # Each commit starts with the message expanded — collapse state
        # is per-commit, not per-session. The toggle expands the view itself.
        self._msg_toggle.setChecked(True)
        self._msg_view.show_message(msg)

        # Files — no auto-selection; show all files' hunks as bordered blocks
        self._diff_model.reload(self._apply_path_filter(files))
        self._render_all_files(oid)

    def _show_commit_header(self, oid: str, commit: Commit, branches: list[Branch]) -> None:
        """Show the header with a badge for each branch at `oid`.

        The header is told which branches are remote and which is checked
        out, because the name cannot say: a local branch can hold a slash too.
        """
        self._detail.set_commit(
            commit,
            [b.name for b in branches if b.target_oid == oid],
            head_branch=next((b.name for b in branches if b.is_head and not b.is_remote), None),
            remote_branches=frozenset(b.name for b in branches if b.is_remote),
        )

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
        hide_hunks_if_collapsed(inner)
        self._sync_hscroll()

    def _on_file_selected(self, index) -> None:
        if self._current_oid is None:
            return
        if not index.isValid():
            # A cleared selection is followed by `deselected`, which redraws
            # all files; drawing them here too fetched every diff twice.
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

        # Each block is a frame subtree registered with the theme manager, and
        # building one per file held the window for seconds on a commit that
        # touches thousands. The rest stay reachable through the file list.
        row_count = self._diff_model.rowCount()
        for row in range(min(row_count, MAX_AGGREGATE_FILE_BLOCKS)):
            index = self._diff_model.index(row)
            file_status = self._diff_model.data(index, Qt.UserRole)
            if file_status is None:
                continue
            path = file_status.path
            frame, inner, skeleton = self._build_skeleton_block(path)
            self._diff_layout.addWidget(frame)
            block_refs.append((path, frame, inner, skeleton))
        if row_count > MAX_AGGREGATE_FILE_BLOCKS:
            self._diff_layout.addWidget(make_overflow_notice(row_count - MAX_AGGREGATE_FILE_BLOCKS))

        self._diff_layout.addStretch()

        self._loader.set_blocks(block_refs)
        self._blocks_generation += 1
        generation = self._blocks_generation

        # Dispatch background fetch
        queries = self._queries

        class _MapSignals(QObject):
            done = Signal(object, int)  # dict, blocks generation

        signals = _MapSignals()
        signals.done.connect(self._on_diff_map_loaded)
        self._diff_map_signals = signals  # prevent GC

        def _worker():
            try:
                result = queries.get_commit_diff_map.execute(oid)
            except Exception:
                logger.warning("Failed to load the diffs of commit %r", oid, exc_info=True)
                result = {}
            signals.done.emit(result, generation)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_diff_map_loaded(self, diff_map: dict, generation: int) -> None:
        if generation == self._blocks_generation:
            self._loader.set_diff_map(diff_map)
