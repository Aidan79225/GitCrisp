# git_gui/presentation/widgets/diff.py
from __future__ import annotations
from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QTextBlockFormat, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QListView, QPlainTextEdit, QSplitter, QStyledItemDelegate,
    QStyleOptionViewItem, QVBoxLayout, QWidget,
)
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.diff_model import DiffModel
from git_gui.presentation.widgets.commit_detail import CommitDetailWidget
from git_gui.presentation.widgets.file_list_view import FileListView as _FileListView

_DELTA_BADGE = {
    "modified": ("M", "#1f6feb"),   # blue
    "added":    ("A", "#238636"),   # green
    "deleted":  ("D", "#da3633"),   # red
    "renamed":  ("R", "#f0883e"),   # orange
    "unknown":  ("?", "#8b949e"),   # gray
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
            painter.fillRect(rect, QColor("#264f78"))

        fs = index.data(Qt.UserRole)
        delta = fs.delta if fs else "unknown"
        label, color = _DELTA_BADGE.get(delta, ("?", "#8b949e"))

        badge_x = rect.left() + 4
        badge_y = rect.top() + (rect.height() - BADGE_SIZE) // 2
        badge_rect = QRect(badge_x, badge_y, BADGE_SIZE, BADGE_SIZE)
        painter.setBrush(QBrush(QColor(color)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(badge_rect, 3, 3)

        painter.setPen(QColor("white"))
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

        # ── Row 2: full commit message ──────────────────────────────────────
        self._msg_view = QPlainTextEdit()
        self._msg_view.setReadOnly(True)
        self._msg_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._msg_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._msg_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._msg_view.viewport().installEventFilter(self)
        self._msg_view.document().setDocumentMargin(8)
        font = self._msg_view.font()
        font.setFamily("Courier New")
        self._msg_view.setFont(font)

        # ── Row 3: file list ────────────────────────────────────────────────
        self._file_view = _FileListView()
        self._file_view.setEditTriggers(QListView.NoEditTriggers)
        self._file_view.setItemDelegate(_FileDeltaDelegate(self._file_view))
        self._diff_view = self._make_diff_editor()
        self._diff_model = DiffModel([])
        self._file_view.setModel(self._diff_model)
        self._file_view.selectionModel().currentChanged.connect(
            self._on_file_selected
        )
        self._file_view.deselected.connect(self._on_file_deselected)

        # ── Row 3+4: file list + diff in splitter ───────────────────────────
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._file_view)
        splitter.addWidget(self._diff_view)
        splitter.setSizes([160, 400])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._detail, 0)
        layout.addWidget(self._msg_view, 0)
        layout.addWidget(splitter, 1)

        # Diff render formats
        self._fmt_added = QTextCharFormat()
        self._fmt_added.setForeground(QColor("white"))
        self._fmt_removed = QTextCharFormat()
        self._fmt_removed.setForeground(QColor("white"))
        self._fmt_header = QTextCharFormat()
        self._fmt_header.setForeground(QColor("#58a6ff"))
        self._fmt_default = QTextCharFormat()
        self._fmt_default.setForeground(QColor("white"))

        self._blk_added = QTextBlockFormat()
        self._blk_added.setBackground(QColor(35, 134, 54, 80))
        self._blk_removed = QTextBlockFormat()
        self._blk_removed.setBackground(QColor(248, 81, 73, 80))
        self._blk_default = QTextBlockFormat()

    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._current_oid = None
        self._detail.clear()
        self._msg_view.clear()
        self._diff_model.reload([])
        self._diff_view.clear()

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

        # Files — no auto-selection; show all files' hunks concatenated
        files = self._queries.get_commit_files.execute(oid)
        self._diff_model.reload(files)
        self._render_all_files(oid)

    def _make_diff_editor(self) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = editor.font()
        font.setFamily("Courier New")
        editor.setFont(font)
        return editor

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
        self._render_single_file(hunks)

    def _on_file_deselected(self) -> None:
        """Return to all-files view when the user click-deselects the current row."""
        if self._current_oid is not None:
            self._render_all_files(self._current_oid)

    @staticmethod
    def _parse_hunk_header(header: str) -> tuple[int, int]:
        import re
        m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", header)
        if m:
            return int(m.group(1)), int(m.group(2))
        return 1, 1

    def _render_diff(self, hunks, cursor) -> None:
        """Append *hunks* to *cursor* without clearing the view first."""
        for hunk in hunks:
            cursor.setBlockFormat(self._blk_default)
            cursor.setCharFormat(self._fmt_header)
            cursor.insertText(hunk.header + "\n")

            old_line, new_line = self._parse_hunk_header(hunk.header)
            for origin, content in hunk.lines:
                if origin == "+":
                    cursor.setBlockFormat(self._blk_added)
                    cursor.setCharFormat(self._fmt_added)
                    prefix = f"     {new_line:>4}  "
                    new_line += 1
                elif origin == "-":
                    cursor.setBlockFormat(self._blk_removed)
                    cursor.setCharFormat(self._fmt_removed)
                    prefix = f"{old_line:>4}       "
                    old_line += 1
                else:
                    cursor.setBlockFormat(self._blk_default)
                    cursor.setCharFormat(self._fmt_default)
                    prefix = f"{old_line:>4} {new_line:>4}  "
                    old_line += 1
                    new_line += 1
                line = content if content.endswith("\n") else content + "\n"
                cursor.insertText(prefix + line)

    def _render_single_file(self, hunks) -> None:
        """Clear the diff view and render one file's hunks."""
        self._diff_view.clear()
        cursor = self._diff_view.textCursor()
        self._render_diff(hunks, cursor)
        self._diff_view.moveCursor(QTextCursor.Start)
        self._diff_view.verticalScrollBar().setValue(0)

    def _render_all_files(self, oid: str) -> None:
        """Clear the diff view and render every file's hunks with file headers."""
        self._diff_view.clear()
        cursor = self._diff_view.textCursor()

        # Format for the bold-ish file header line
        fmt_file_header = QTextCharFormat()
        fmt_file_header.setForeground(QColor("#e3b341"))   # amber — distinct from hunk headers

        row_count = self._diff_model.rowCount()
        for row in range(row_count):
            index = self._diff_model.index(row)
            file_status = self._diff_model.data(index, Qt.UserRole)
            if file_status is None:
                continue
            path = file_status.path

            # Blank separator before every file header except the first
            if row > 0:
                cursor.setBlockFormat(self._blk_default)
                cursor.setCharFormat(self._fmt_default)
                cursor.insertText("\n")

            cursor.setBlockFormat(self._blk_default)
            cursor.setCharFormat(fmt_file_header)
            cursor.insertText(f"📄 {path}\n")

            hunks = self._queries.get_file_diff.execute(oid, path)
            self._render_diff(hunks, cursor)

        self._diff_view.moveCursor(QTextCursor.Start)
        self._diff_view.verticalScrollBar().setValue(0)
