# git_gui/presentation/widgets/working_tree.py
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QListView, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import FileStatus, WORKING_TREE_OID
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.widgets.working_tree_model import WorkingTreeModel
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget


class WorkingTreeWidget(QWidget):
    reload_requested = Signal()
    commit_completed = Signal(str)   # emits first line of commit message
    commit_failed = Signal(str)      # emits error reason

    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands

        # ── Row 1: commit toolbar ────────────────────────────────────────────
        self._msg_edit = QPlainTextEdit()
        self._msg_edit.setPlaceholderText("Commit message...")
        self._msg_edit.setMaximumHeight(80)

        self._btn_stage_all = QPushButton("Stage All")
        self._btn_unstage_all = QPushButton("Unstage All")
        self._btn_commit = QPushButton("Commit")

        btn_layout = QVBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addWidget(self._btn_stage_all)
        btn_layout.addWidget(self._btn_unstage_all)
        btn_layout.addWidget(self._btn_commit)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(4, 4, 4, 4)
        toolbar_layout.addWidget(self._msg_edit, 1)
        toolbar_layout.addLayout(btn_layout)

        # ── Row 2: file list ─────────────────────────────────────────────────
        self._file_view = QListView()
        self._file_view.setEditTriggers(QListView.NoEditTriggers)

        self._file_model = WorkingTreeModel(commands, self)
        self._file_view.setModel(self._file_model)
        self._file_view.selectionModel().currentChanged.connect(self._on_file_selected)

        # ── Row 3: hunk diff ─────────────────────────────────────────────────
        self._hunk_diff = HunkDiffWidget(queries, commands, self)

        # ── Splitter ─────────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(toolbar)
        splitter.addWidget(self._file_view)
        splitter.addWidget(self._hunk_diff)
        splitter.setSizes([80, 120, 10000])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        # ── Signals ──────────────────────────────────────────────────────────
        self._btn_stage_all.clicked.connect(self._on_stage_all)
        self._btn_unstage_all.clicked.connect(self._on_unstage_all)
        self._btn_commit.clicked.connect(self._on_commit)
        self._file_model.files_changed.connect(self._on_files_changed)
        self._hunk_diff.hunk_toggled.connect(self._on_files_changed)

    def reload(self) -> None:
        files = self._queries.get_working_tree.execute()
        partial = self._detect_partial(files)
        self._file_model.reload(files, partial)
        self._hunk_diff.clear()

    def _detect_partial(self, files: list[FileStatus]) -> set[str]:
        """Detect files with partial staging (some hunks staged, some not)."""
        partial: set[str] = set()
        seen = set()
        for f in files:
            if f.path in seen:
                # File appears in both staged and unstaged lists
                partial.add(f.path)
            seen.add(f.path)
        # Also check files that appear once but have hunks in both states
        staged_paths = {f.path for f in files if f.status == "staged"}
        unstaged_paths = {f.path for f in files if f.status != "staged"}
        for path in staged_paths - partial:
            if self._queries.get_file_diff.execute(WORKING_TREE_OID, path):
                partial.add(path)
        for path in unstaged_paths - partial:
            if self._queries.get_staged_diff.execute(path):
                partial.add(path)
        return partial

    def _on_file_selected(self, current, previous) -> None:
        if not current.isValid():
            return
        fs = self._file_model.data(current, Qt.UserRole)
        if fs is None:
            return
        self._hunk_diff.load_file(fs.path)

    def _on_stage_all(self) -> None:
        files = self._queries.get_working_tree.execute()
        # Stage all unstaged files + partially staged files (re-stage to pick up remaining hunks)
        partial = self._detect_partial(files)
        paths = list({f.path for f in files if f.status != "staged"} | partial)
        if paths:
            self._commands.stage_files.execute(paths)
            self._on_files_changed()

    def _on_unstage_all(self) -> None:
        files = self._queries.get_working_tree.execute()
        # Unstage all staged files + partially staged files
        partial = self._detect_partial(files)
        paths = list({f.path for f in files if f.status == "staged"} | partial)
        if paths:
            self._commands.unstage_files.execute(paths)
            self._on_files_changed()

    def _on_commit(self) -> None:
        msg = self._msg_edit.toPlainText().strip()
        if not msg:
            self.commit_failed.emit("Commit message is empty")
            return
        self._commands.create_commit.execute(msg)
        first_line = msg.split("\n")[0]
        self._msg_edit.clear()
        self.commit_completed.emit(first_line)
        self.reload_requested.emit()
        self.reload()

    def _on_files_changed(self) -> None:
        # Remember selected path before reload clears selection
        selected_path = None
        idx = self._file_view.currentIndex()
        if idx.isValid():
            fs = self._file_model.data(idx, Qt.UserRole)
            if fs:
                selected_path = fs.path

        files = self._queries.get_working_tree.execute()
        partial = self._detect_partial(files)
        self._file_model.reload(files, partial)

        # Restore selection by path and refresh hunk diff
        if selected_path:
            for row in range(self._file_model.rowCount()):
                fs = self._file_model.data(self._file_model.index(row), Qt.UserRole)
                if fs and fs.path == selected_path:
                    self._file_view.setCurrentIndex(self._file_model.index(row))
                    self._hunk_diff.load_file(selected_path)
                    return
        self._hunk_diff.clear()
