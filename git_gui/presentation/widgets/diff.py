# git_gui/presentation/widgets/diff.py
from __future__ import annotations
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import (
    QListView, QPlainTextEdit, QSplitter, QStyledItemDelegate,
    QStyleOptionViewItem, QVBoxLayout, QWidget,
)
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.diff_model import DiffModel

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

        # Selection highlight
        from PySide6.QtWidgets import QStyle
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor("#264f78"))

        # Get delta type from FileStatus
        fs = index.data(Qt.UserRole)
        delta = fs.delta if fs else "unknown"
        label, color = _DELTA_BADGE.get(delta, ("?", "#8b949e"))

        # Draw badge
        badge_x = rect.left() + 4
        badge_y = rect.top() + (rect.height() - BADGE_SIZE) // 2
        badge_rect = QRect(badge_x, badge_y, BADGE_SIZE, BADGE_SIZE)
        painter.setBrush(QBrush(QColor(color)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(badge_rect, 3, 3)

        # Badge text
        painter.setPen(QColor("white"))
        painter.drawText(badge_rect, Qt.AlignCenter, label)

        # File path
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

        self._file_view = QListView()
        self._file_view.setEditTriggers(QListView.NoEditTriggers)
        self._file_view.setItemDelegate(_FileDeltaDelegate(self._file_view))
        self._diff_view = self._make_diff_editor()
        self._diff_model = DiffModel([])
        self._file_view.setModel(self._diff_model)
        self._file_view.selectionModel().currentChanged.connect(
            self._on_file_selected
        )

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._file_view)
        splitter.addWidget(self._diff_view)
        splitter.setSizes([200, 400])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

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

    def load_commit(self, oid: str) -> None:
        self._current_oid = oid
        files = self._queries.get_commit_files.execute(oid)
        self._diff_model.reload(files)
        self._diff_view.clear()
        if files:
            self._file_view.setCurrentIndex(self._diff_model.index(0))

    def _make_diff_editor(self) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = editor.font()
        font.setFamily("Courier New")
        editor.setFont(font)
        return editor

    def _on_file_selected(self, index) -> None:
        if not index.isValid() or self._current_oid is None:
            return
        file_status = self._diff_model.data(index, Qt.UserRole)
        if file_status is None:
            return
        hunks = self._queries.get_file_diff.execute(self._current_oid, file_status.path)
        self._render_diff(hunks)

    @staticmethod
    def _parse_hunk_header(header: str) -> tuple[int, int]:
        """Parse '@@ -old_start,old_count +new_start,new_count @@' into (old_start, new_start)."""
        import re
        m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", header)
        if m:
            return int(m.group(1)), int(m.group(2))
        return 1, 1

    def _render_diff(self, hunks) -> None:
        self._diff_view.clear()
        cursor = self._diff_view.textCursor()
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
        self._diff_view.setTextCursor(cursor)
