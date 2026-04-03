# git_gui/presentation/widgets/diff.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import (
    QListView, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget,
)
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.diff_model import DiffModel


class DiffWidget(QWidget):
    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._current_oid: str | None = None

        self._file_view = QListView()
        self._file_view.setEditTriggers(QListView.NoEditTriggers)
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

    def _render_diff(self, hunks) -> None:
        self._diff_view.clear()
        cursor = self._diff_view.textCursor()
        for hunk in hunks:
            cursor.setBlockFormat(self._blk_default)
            cursor.setCharFormat(self._fmt_header)
            cursor.insertText(hunk.header + "\n")
            for origin, content in hunk.lines:
                if origin == "+":
                    cursor.setBlockFormat(self._blk_added)
                    cursor.setCharFormat(self._fmt_added)
                elif origin == "-":
                    cursor.setBlockFormat(self._blk_removed)
                    cursor.setCharFormat(self._fmt_removed)
                else:
                    cursor.setBlockFormat(self._blk_default)
                    cursor.setCharFormat(self._fmt_default)
                cursor.insertText(content if content.endswith("\n") else content + "\n")
        self._diff_view.setTextCursor(cursor)
