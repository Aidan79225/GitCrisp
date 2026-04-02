# git_gui/presentation/widgets/diff.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QListView, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.diff_model import DiffModel


class DiffWidget(QWidget):
    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._current_oid: str | None = None

        self._file_view = QListView()
        self._file_view.setEditTriggers(QListView.NoEditTriggers)

        self._diff_view = QPlainTextEdit()
        self._diff_view.setReadOnly(True)
        self._diff_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = self._diff_view.font()
        font.setFamily("Courier New")
        self._diff_view.setFont(font)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._file_view)
        splitter.addWidget(self._diff_view)
        splitter.setSizes([200, 400])

        self._diff_model = DiffModel([])
        self._file_view.setModel(self._diff_model)
        self._file_view.selectionModel().currentChanged.connect(self._on_file_selected)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def load_commit(self, oid: str) -> None:
        self._current_oid = oid
        self._diff_view.clear()
        if oid == WORKING_TREE_OID:
            files = self._queries.get_working_tree.execute()
        else:
            files = self._queries.get_commit_files.execute(oid)
        self._diff_model.reload(files)
        if files:
            self._file_view.setCurrentIndex(self._diff_model.index(0))

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
        added_fmt = QTextCharFormat()
        added_fmt.setForeground(QColor("#2ea043"))
        removed_fmt = QTextCharFormat()
        removed_fmt.setForeground(QColor("#f85149"))
        header_fmt = QTextCharFormat()
        header_fmt.setForeground(QColor("#58a6ff"))
        default_fmt = QTextCharFormat()

        for hunk in hunks:
            cursor.setCharFormat(header_fmt)
            cursor.insertText(hunk.header + "\n")
            for origin, content in hunk.lines:
                if origin == "+":
                    cursor.setCharFormat(added_fmt)
                elif origin == "-":
                    cursor.setCharFormat(removed_fmt)
                else:
                    cursor.setCharFormat(default_fmt)
                cursor.insertText(content if content.endswith("\n") else content + "\n")

        self._diff_view.setTextCursor(cursor)
