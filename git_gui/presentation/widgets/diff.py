# git_gui/presentation/widgets/diff.py
from __future__ import annotations
from PySide6.QtCore import QEvent, QRect, QSize, Qt
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
    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._current_oid: str | None = None

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

        self._diff_model = DiffModel([])
        self._file_view.setModel(self._diff_model)
        self._file_view.selectionModel().currentChanged.connect(
            self._on_file_selected
        )
        self._file_view.deselected.connect(self._on_file_deselected)

        # ── Row 3+4: file list + diff in splitter ───────────────────────────
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._file_view)
        splitter.addWidget(self._diff_scroll)
        splitter.setSizes([160, 400])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        layout.addWidget(self._detail, 0)
        layout.addWidget(self._msg_view, 0)
        layout.addWidget(splitter, 1)

        # Diff render formats
        self._formats = make_diff_formats()

        self._restyle_themed_panels()
        connect_widget(self, rebuild=self._on_theme_changed)

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

    def eventFilter(self, obj, event):
        if obj is self._msg_view.viewport() and event.type() in (
            QEvent.Wheel, QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease, QEvent.MouseMove,
        ):
            return True  # block all mouse interaction on commit message
        return super().eventFilter(obj, event)

    def load_commit(self, oid: str) -> None:
        self._current_oid = oid

        # Fetch commit detail + refs
        commit = self._queries.get_commit_detail.execute(oid)
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

    def _build_file_block(self, path: str, hunks):
        """Build and return a bordered QFrame containing a file header and per-hunk widgets."""
        frame, inner = make_file_block(path)

        for hunk in hunks:
            add_hunk_widget(inner, hunk, self._formats)

        return frame

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
        self._clear_blocks()
        block = self._build_file_block(path, hunks)
        self._diff_layout.addWidget(block)
        self._diff_layout.addStretch()
        self._diff_scroll.verticalScrollBar().setValue(0)

    def _render_all_files(self, oid: str) -> None:
        """Clear and render every file as a bordered block."""
        self._clear_blocks()

        row_count = self._diff_model.rowCount()
        for row in range(row_count):
            index = self._diff_model.index(row)
            file_status = self._diff_model.data(index, Qt.UserRole)
            if file_status is None:
                continue
            path = file_status.path
            hunks = self._queries.get_file_diff.execute(oid, path)
            block = self._build_file_block(path, hunks)
            self._diff_layout.addWidget(block)

        self._diff_layout.addStretch()
        self._diff_scroll.verticalScrollBar().setValue(0)
