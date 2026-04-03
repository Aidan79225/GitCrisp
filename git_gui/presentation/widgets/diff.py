# git_gui/presentation/widgets/diff.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor, QStandardItem, QStandardItemModel,
    QTextBlockFormat, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QLabel, QListView, QPlainTextEdit, QSplitter, QStackedWidget,
    QTreeView, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.models.diff_model import DiffModel


class DiffWidget(QWidget):
    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands
        self._current_oid: str | None = None

        # ── commit mode (stack page 0) ──────────────────────────────────────
        self._commit_file_view = QListView()
        self._commit_file_view.setEditTriggers(QListView.NoEditTriggers)
        self._commit_diff_view = self._make_diff_editor()
        self._commit_diff_model = DiffModel([])
        self._commit_file_view.setModel(self._commit_diff_model)
        self._commit_file_view.selectionModel().currentChanged.connect(
            self._on_commit_file_selected
        )

        commit_splitter = QSplitter(Qt.Vertical)
        commit_splitter.addWidget(self._commit_file_view)
        commit_splitter.addWidget(self._commit_diff_view)
        commit_splitter.setSizes([200, 400])

        commit_page = QWidget()
        commit_layout = QVBoxLayout(commit_page)
        commit_layout.setContentsMargins(0, 0, 0, 0)
        commit_layout.addWidget(commit_splitter)

        # ── working tree mode (stack page 1) ────────────────────────────────
        self._wt_tree = QTreeView()
        self._wt_tree.setHeaderHidden(True)
        self._wt_tree.setEditTriggers(QTreeView.NoEditTriggers)
        self._wt_model = QStandardItemModel()
        self._wt_tree.setModel(self._wt_model)
        self._wt_tree.selectionModel().currentChanged.connect(self._on_wt_file_selected)

        staged_label = QLabel("Staged Changes")
        self._staged_diff_view = self._make_diff_editor()
        unstaged_label = QLabel("Unstaged Changes")
        self._unstaged_diff_view = self._make_diff_editor()

        staged_container = QWidget()
        staged_layout = QVBoxLayout(staged_container)
        staged_layout.setContentsMargins(4, 4, 4, 0)
        staged_layout.addWidget(staged_label)
        staged_layout.addWidget(self._staged_diff_view)

        unstaged_container = QWidget()
        unstaged_layout = QVBoxLayout(unstaged_container)
        unstaged_layout.setContentsMargins(4, 4, 4, 0)
        unstaged_layout.addWidget(unstaged_label)
        unstaged_layout.addWidget(self._unstaged_diff_view)

        diff_splitter = QSplitter(Qt.Vertical)
        diff_splitter.addWidget(staged_container)
        diff_splitter.addWidget(unstaged_container)
        diff_splitter.setSizes([300, 300])

        wt_splitter = QSplitter(Qt.Horizontal)
        wt_splitter.addWidget(self._wt_tree)
        wt_splitter.addWidget(diff_splitter)
        wt_splitter.setSizes([200, 600])

        wt_page = QWidget()
        wt_layout = QVBoxLayout(wt_page)
        wt_layout.setContentsMargins(0, 0, 0, 0)
        wt_layout.addWidget(wt_splitter)

        # ── stack ────────────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.addWidget(commit_page)   # index 0: commit mode
        self._stack.addWidget(wt_page)       # index 1: working tree mode

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        # Diff render formats (created once, reused per render)
        self._fmt_added = QTextCharFormat()
        self._fmt_added.setForeground(QColor("white"))
        self._fmt_removed = QTextCharFormat()
        self._fmt_removed.setForeground(QColor("white"))
        self._fmt_header = QTextCharFormat()
        self._fmt_header.setForeground(QColor("#58a6ff"))
        self._fmt_default = QTextCharFormat()
        self._fmt_default.setForeground(QColor("white"))

        # Block formats for full-row background highlighting
        self._blk_added = QTextBlockFormat()
        self._blk_added.setBackground(QColor(35, 134, 54, 80))
        self._blk_removed = QTextBlockFormat()
        self._blk_removed.setBackground(QColor(248, 81, 73, 80))
        self._blk_default = QTextBlockFormat()

    # ── public ───────────────────────────────────────────────────────────────

    def load_commit(self, oid: str) -> None:
        self._current_oid = oid
        if oid == WORKING_TREE_OID:
            self._stack.setCurrentIndex(1)
            self._load_working_tree()
        else:
            self._stack.setCurrentIndex(0)
            files = self._queries.get_commit_files.execute(oid)
            self._commit_diff_model.reload(files)
            self._commit_diff_view.clear()
            if files:
                self._commit_file_view.setCurrentIndex(self._commit_diff_model.index(0))

    # ── private ──────────────────────────────────────────────────────────────

    def _make_diff_editor(self) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = editor.font()
        font.setFamily("Courier New")
        editor.setFont(font)
        return editor

    def _load_working_tree(self) -> None:
        self._wt_model.clear()
        files = self._queries.get_working_tree.execute()
        staged = [f for f in files if f.status == "staged"]
        unstaged = [f for f in files if f.status in ("unstaged", "untracked", "conflicted")]

        for title, section_files in [("STAGED", staged), ("UNSTAGED", unstaged)]:
            header = QStandardItem(title)
            header.setEditable(False)
            header.setSelectable(False)
            header.setData("header", Qt.UserRole + 1)
            for f in section_files:
                item = QStandardItem(f.path)
                item.setEditable(False)
                item.setData(f, Qt.UserRole)
                header.appendRow(item)
            self._wt_model.appendRow(header)

        self._wt_tree.expandAll()
        self._staged_diff_view.clear()
        self._unstaged_diff_view.clear()

    def _on_commit_file_selected(self, index) -> None:
        if not index.isValid() or self._current_oid is None:
            return
        file_status = self._commit_diff_model.data(index, Qt.UserRole)
        if file_status is None:
            return
        hunks = self._queries.get_file_diff.execute(self._current_oid, file_status.path)
        self._render_diff(self._commit_diff_view, hunks)

    def _on_wt_file_selected(self, index) -> None:
        if not index.isValid():
            return
        file_status = index.data(Qt.UserRole)
        if file_status is None:
            return  # section header clicked — nothing to show
        path = file_status.path
        self._render_diff(
            self._staged_diff_view,
            self._queries.get_staged_diff.execute(path),
        )
        # get_file_diff(WORKING_TREE_OID, path) diffs the working tree against the index (unstaged changes)
        self._render_diff(
            self._unstaged_diff_view,
            self._queries.get_file_diff.execute(WORKING_TREE_OID, path),
        )

    def _render_diff(self, editor: QPlainTextEdit, hunks) -> None:
        editor.clear()
        cursor = editor.textCursor()
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
        editor.setTextCursor(cursor)
