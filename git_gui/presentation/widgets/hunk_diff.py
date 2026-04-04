# git_gui/presentation/widgets/hunk_diff.py
from __future__ import annotations
import threading
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import (
    QCheckBox, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import Hunk
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.domain.entities import WORKING_TREE_OID


class _LoadSignals(QObject):
    done = Signal(str, list, list)  # path, staged_hunks, unstaged_hunks


class HunkDiffWidget(QWidget):
    hunk_toggled = Signal()

    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands
        self._current_path: str | None = None

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 8, 4, 4)
        self._scroll.setWidget(self._container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)

        # Diff formats
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
        self._commands = commands
        if queries is None:
            self.clear()

    def load_file(self, path: str) -> None:
        self._current_path = path
        self._fetch_and_render()

    def clear(self) -> None:
        self._current_path = None
        self._clear_layout()

    def _fetch_and_render(self) -> None:
        if self._current_path is None:
            return
        path = self._current_path
        queries = self._queries

        signals = _LoadSignals()
        signals.done.connect(self._on_load_done)
        self._load_signals = signals  # prevent GC

        def _worker():
            staged_hunks = queries.get_staged_diff.execute(path)
            unstaged_hunks = queries.get_file_diff.execute(WORKING_TREE_OID, path)
            signals.done.emit(path, staged_hunks, unstaged_hunks)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_load_done(self, path: str, staged_hunks: list[Hunk],
                      unstaged_hunks: list[Hunk]) -> None:
        # Discard if user already navigated to a different file
        if path != self._current_path:
            return

        self._clear_layout()

        for hunk in staged_hunks:
            self._add_hunk_block(hunk, is_staged=True)
        for hunk in unstaged_hunks:
            self._add_hunk_block(hunk, is_staged=False)

        self._layout.addStretch()

    def _render_sync(self) -> None:
        """Synchronous render — used after hunk toggle where data is already changing."""
        self._clear_layout()
        if self._current_path is None:
            return

        staged_hunks = self._queries.get_staged_diff.execute(self._current_path)
        unstaged_hunks = self._queries.get_file_diff.execute(
            WORKING_TREE_OID, self._current_path
        )

        for hunk in staged_hunks:
            self._add_hunk_block(hunk, is_staged=True)
        for hunk in unstaged_hunks:
            self._add_hunk_block(hunk, is_staged=False)

        self._layout.addStretch()

    def _add_hunk_block(self, hunk: Hunk, is_staged: bool) -> None:
        checkbox = QCheckBox(hunk.header.strip())
        checkbox.setChecked(is_staged)

        path = self._current_path
        header = hunk.header
        checkbox.toggled.connect(
            lambda checked, p=path, h=header: self._on_hunk_toggled(p, h, checked)
        )

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        font = editor.font()
        font.setFamily("Courier New")
        editor.setFont(font)

        old_line, new_line = self._parse_hunk_header(hunk.header)
        cursor = editor.textCursor()
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
        editor.setTextCursor(cursor)

        # Size to fit all lines — calculated from line count + font metrics
        line_height = editor.fontMetrics().lineSpacing()
        margins = editor.contentsMargins()
        doc_margin = editor.document().documentMargin() * 2
        total_height = int(len(hunk.lines) * line_height + doc_margin + margins.top() + margins.bottom() + 4)
        editor.setFixedHeight(total_height)

        self._layout.addWidget(checkbox)
        self._layout.addWidget(editor)

    @staticmethod
    def _parse_hunk_header(header: str) -> tuple[int, int]:
        import re
        m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", header)
        if m:
            return int(m.group(1)), int(m.group(2))
        return 1, 1

    def _on_hunk_toggled(self, path: str, hunk_header: str, checked: bool) -> None:
        if checked:
            self._commands.stage_hunk.execute(path, hunk_header)
        else:
            self._commands.unstage_hunk.execute(path, hunk_header)
        self._render_sync()
        self.hunk_toggled.emit()

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
