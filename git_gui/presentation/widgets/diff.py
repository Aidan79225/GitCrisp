# git_gui/presentation/widgets/diff.py
from __future__ import annotations
import logging
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import (
    QListView, QPlainTextEdit, QScrollArea, QSplitter,
    QStyledItemDelegate, QStyleOptionViewItem, QVBoxLayout, QWidget,
)
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.theme import get_theme_manager, connect_widget
from git_gui.presentation.models.diff_model import DiffModel
from git_gui.presentation.widgets.commit_detail import CommitDetailWidget
from git_gui.presentation.widgets.file_list_view import FileListView as _FileListView
from git_gui.presentation.widgets.diff_block import (
    make_file_block, make_diff_formats, add_hunk_widget,
)

logger = logging.getLogger(__name__)

# (label only — color comes from theme.colors.status_color(kind) at paint time)
_DELTA_LABEL = {
    "modified": "M",
    "added":    "A",
    "deleted":  "D",
    "renamed":  "R",
    "unknown":  "?",
}

BADGE_SIZE = 20
BADGE_GAP = 6


class _FileDeltaDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect

        from PySide6.QtWidgets import QStyle
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, get_theme_manager().current.colors.as_qcolor("primary"))

        fs = index.data(Qt.UserRole)
        delta = fs.delta if fs else "unknown"
        label = _DELTA_LABEL.get(delta, "?")

        badge_x = rect.left() + 4
        badge_y = rect.top() + (rect.height() - BADGE_SIZE) // 2
        badge_rect = QRect(badge_x, badge_y, BADGE_SIZE, BADGE_SIZE)
        painter.setBrush(QBrush(get_theme_manager().current.colors.status_color(delta)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(badge_rect, 3, 3)

        painter.setPen(get_theme_manager().current.colors.as_qcolor("on_badge"))
        painter.drawText(badge_rect, Qt.AlignCenter, label)

        text_x = badge_x + BADGE_SIZE + BADGE_GAP
        text_rect = QRect(text_x, rect.top(), rect.right() - text_x, rect.height())
        painter.setPen(option.palette.text().color())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, index.data(Qt.DisplayRole) or "")

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), max(BADGE_SIZE + 8, option.fontMetrics.height() + 8))


class DiffWidget(QWidget):
    submodule_open_requested = Signal(str)  # emits the submodule path (relative)

    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._current_oid: str | None = None
        self._submodule_paths: set[str] = set()

        # Lazy loading state
        self._diff_map: dict[str, list] = {}
        # Each entry: (path, frame_widget, inner_layout, skeleton_widget_or_none)
        self._block_refs: list[tuple[str, QWidget, object, object]] = []
        self._loaded_paths: set[str] = set()

        # Scroll debounce timer
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._check_viewport_and_load)

        # ── Row 1: commit detail (3-line metadata) ──────────────────────────
        self._detail = CommitDetailWidget()
        self._detail.setAutoFillBackground(True)

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

        # ── Row 3: file list ────────────────────────────────────────────────
        self._file_view = _FileListView()
        self._file_view.setEditTriggers(QListView.NoEditTriggers)
        self._file_view.setItemDelegate(_FileDeltaDelegate(self._file_view))

        # ── Diff area: scrollable container of per-file bordered blocks ─────
        self._diff_scroll = QScrollArea()
        self._diff_scroll.setWidgetResizable(True)
        self._diff_container = QWidget()
        self._diff_layout = QVBoxLayout(self._diff_container)
        self._diff_layout.setContentsMargins(0, 4, 0, 4)
        self._diff_layout.setSpacing(8)
        self._diff_scroll.setWidget(self._diff_container)
        self._diff_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        self._diff_model = DiffModel([])
        self._file_view.setModel(self._diff_model)
        self._file_view.selectionModel().currentChanged.connect(
            self._on_file_selected
        )
        self._file_view.deselected.connect(self._on_file_deselected)

        # ── Row 3+4: file list + diff in splitter ───────────────────────────
        self._splitter = QSplitter(Qt.Vertical)
        self._splitter.addWidget(self._file_view)
        self._splitter.addWidget(self._diff_scroll)
        self._splitter.setSizes([160, 400])
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        layout.addWidget(self._detail, 0)
        layout.addWidget(self._msg_view, 0)
        layout.addWidget(self._splitter, 1)

        # Diff render formats
        self._formats = make_diff_formats()

        self._restyle_themed_panels()
        connect_widget(self, rebuild=self._on_theme_changed)

        # Start in empty state — nothing to show until a commit is loaded.
        self._set_empty_state(True)

    def _set_empty_state(self, empty: bool) -> None:
        """Hide or show all sub-panels based on whether a commit is loaded."""
        self._detail.setVisible(not empty)
        self._msg_view.setVisible(not empty)
        self._splitter.setVisible(not empty)

    def _on_theme_changed(self) -> None:
        self._formats = make_diff_formats()
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
        self._file_view.setStyleSheet(
            f"QListView {{ background: {bg}; "
            f"border: 1px solid {outline}; border-radius: 4px; padding: 6px; }}"
        )

    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._current_oid = None
        self._detail.clear()
        self._msg_view.clear()
        self._diff_model.reload([])
        self._clear_blocks()
        self._set_empty_state(True)

    def eventFilter(self, obj, event):
        if obj is self._msg_view.viewport() and event.type() in (
            QEvent.Wheel, QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease, QEvent.MouseMove,
        ):
            return True  # block all mouse interaction on commit message
        return super().eventFilter(obj, event)

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
        self._msg_view.setPlainText(msg)
        line_count = msg.count("\n") + 1
        line_h = self._msg_view.fontMetrics().lineSpacing()
        doc_margin = self._msg_view.document().documentMargin() * 2
        msg_h = int(line_count * line_h + doc_margin)
        self._msg_view.setFixedHeight(msg_h)

        # Files — no auto-selection; show all files' hunks as bordered blocks
        files = self._queries.get_commit_files.execute(oid)
        self._diff_model.reload(files)
        self._render_all_files(oid)

    # ── Internal helpers ────────────────────────────────────────────────────

    def _clear_blocks(self) -> None:
        """Remove all widgets and items from the diff layout."""
        while self._diff_layout.count():
            item = self._diff_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        # Invalidate tracked block refs — their frames are now deleted.
        # Any pending QTimer callbacks must not touch them.
        self._block_refs = []
        self._loaded_paths = set()

    def _refresh_submodule_paths(self) -> None:
        """Refresh the cached set of submodule paths from the repository."""
        if self._queries is None:
            self._submodule_paths = set()
            return
        try:
            self._submodule_paths = {
                s.path for s in self._queries.list_submodules.execute()
            }
        except Exception:
            self._submodule_paths = set()

    def _build_file_block(self, path: str, hunks):
        """Build and return a bordered QFrame containing a file header and per-hunk widgets."""
        is_submodule = path in self._submodule_paths
        on_click = (
            (lambda p=path: self.submodule_open_requested.emit(p))
            if is_submodule else None
        )
        frame, inner = make_file_block(path, on_header_clicked=on_click)

        for hunk in hunks:
            add_hunk_widget(inner, hunk, self._formats, on_header_clicked=on_click)

        return frame

    def _build_skeleton_block(self, path: str):
        """Build a file block with a skeleton placeholder. Returns (frame, inner, skeleton)."""
        from git_gui.presentation.widgets.diff_block import make_skeleton_container
        is_submodule = path in self._submodule_paths
        on_click = (
            (lambda p=path: self.submodule_open_requested.emit(p))
            if is_submodule else None
        )
        frame, inner = make_file_block(path, on_header_clicked=on_click)
        skeleton = make_skeleton_container()
        inner.addWidget(skeleton)
        return frame, inner, skeleton

    def _on_scroll(self, value: int) -> None:
        """Debounced scroll handler — restart the timer on every scroll."""
        self._scroll_timer.start()

    def _check_viewport_and_load(self) -> None:
        """Realize the first skeleton block intersecting the viewport.

        Only one block per call — after realization, the layout shifts, so we
        reschedule the check via QTimer.singleShot(0, ...) to let Qt process
        the layout before re-checking. This prevents a thundering-herd of
        simultaneous realizations when skeletons are smaller than real hunks.

        If the widget has been reloaded since a check was scheduled, the old
        frames may already be deleted by Qt. A stale frame reference manifests
        as a ``RuntimeError`` from shiboken; we skip those entries silently.
        """
        if not self._block_refs or not self._diff_map:
            return
        try:
            viewport = self._diff_scroll.viewport()
            vp_rect = viewport.rect()
        except RuntimeError:
            return
        for path, frame, inner, skeleton in list(self._block_refs):
            if path in self._loaded_paths:
                continue
            if frame is None:
                continue
            try:
                top_left = frame.mapTo(viewport, QPoint(0, 0))
                frame_rect = frame.rect().translated(top_left)
            except RuntimeError:
                # Frame was deleted by a newer load — stale entry, skip.
                continue
            if frame_rect.intersects(vp_rect):
                self._realize_block(path, inner, skeleton)
                # Re-check after Qt processes the layout change
                QTimer.singleShot(0, self._check_viewport_and_load)
                return

    def _realize_block(self, path: str, inner, skeleton) -> None:
        """Replace the skeleton with real hunk widgets for the given path."""
        if path in self._loaded_paths:
            return
        hunks = self._diff_map.get(path, [])
        # Remove skeleton
        if skeleton is not None:
            inner.removeWidget(skeleton)
            skeleton.deleteLater()
        # Add hunk widgets
        is_submodule = path in self._submodule_paths
        on_click = (
            (lambda p=path: self.submodule_open_requested.emit(p))
            if is_submodule else None
        )
        for hunk in hunks:
            add_hunk_widget(inner, hunk, self._formats, on_header_clicked=on_click)
        self._loaded_paths.add(path)

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
        self._block_refs = []
        self._loaded_paths = set()
        block = self._build_file_block(path, hunks)
        self._diff_layout.addWidget(block)
        self._diff_layout.addStretch()
        self._diff_scroll.verticalScrollBar().setValue(0)

    def _render_all_files(self, oid: str) -> None:
        """Render all file blocks as skeletons immediately, then fetch diffs in background."""
        import threading
        from PySide6.QtCore import QObject, Signal

        self._refresh_submodule_paths()
        self._clear_blocks()
        self._block_refs = []
        self._loaded_paths = set()
        self._diff_map = {}

        row_count = self._diff_model.rowCount()
        for row in range(row_count):
            index = self._diff_model.index(row)
            file_status = self._diff_model.data(index, Qt.UserRole)
            if file_status is None:
                continue
            path = file_status.path
            frame, inner, skeleton = self._build_skeleton_block(path)
            self._diff_layout.addWidget(frame)
            self._block_refs.append((path, frame, inner, skeleton))

        self._diff_layout.addStretch()
        self._diff_scroll.verticalScrollBar().setValue(0)

        # Dispatch background fetch
        queries = self._queries

        class _MapSignals(QObject):
            done = Signal(object)  # dict

        signals = _MapSignals()
        signals.done.connect(self._on_diff_map_loaded)
        self._diff_map_signals = signals  # prevent GC

        def _worker():
            try:
                result = queries.get_commit_diff_map.execute(oid)
            except Exception:
                result = {}
            signals.done.emit(result)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_diff_map_loaded(self, diff_map: dict) -> None:
        """Background fetch finished — store the map and realize visible blocks.

        Defer the viewport check one event loop tick so Qt has a chance to lay
        out the skeleton blocks; otherwise their positions may still be (0, 0)
        and every block would look visible.
        """
        self._diff_map = diff_map
        QTimer.singleShot(0, self._check_viewport_and_load)
