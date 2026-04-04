# git_gui/presentation/widgets/working_tree.py
from __future__ import annotations
import threading
from PySide6.QtCore import QObject, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout, QListView, QPlainTextEdit, QPushButton,
    QSplitter, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QVBoxLayout, QWidget,
)
from git_gui.domain.entities import FileStatus
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.widgets.working_tree_model import WorkingTreeModel
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget

_DELTA_BADGE = {
    "modified": ("M", "#1f6feb"),
    "added":    ("A", "#238636"),
    "deleted":  ("D", "#da3633"),
    "renamed":  ("R", "#f0883e"),
    "unknown":  ("?", "#8b949e"),
}
_BADGE_SIZE = 20
_BADGE_GAP = 6


class _FileDelegate(QStyledItemDelegate):
    """Adds a delta badge between the native checkbox and filename."""

    def initStyleOption(self, option: QStyleOptionViewItem, index) -> None:
        super().initStyleOption(option, index)
        # Prefix badge letter to display text so Qt reserves space;
        # we'll paint the badge over this prefix area
        fs = index.data(Qt.UserRole)
        delta = fs.delta if fs else "unknown"
        label, _ = _DELTA_BADGE.get(delta, ("?", "#8b949e"))
        # Add padding spaces to make room for the badge we'll paint
        option.text = "        " + (option.text or "")

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        # Let Qt draw checkbox + text normally
        super().paint(painter, option, index)

        # Now paint the delta badge in the gap we reserved
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect
        fs = index.data(Qt.UserRole)
        delta = fs.delta if fs else "unknown"
        label, color = _DELTA_BADGE.get(delta, ("?", "#8b949e"))

        # Position badge after the checkbox area (~30px from left)
        badge_x = rect.left() + 30
        badge_y = rect.top() + (rect.height() - _BADGE_SIZE) // 2
        badge_rect = QRect(badge_x, badge_y, _BADGE_SIZE, _BADGE_SIZE)
        painter.setBrush(QBrush(QColor(color)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(badge_rect, 3, 3)
        painter.setPen(QColor("white"))
        painter.drawText(badge_rect, Qt.AlignCenter, label)

        painter.restore()


class _LoadSignals(QObject):
    done = Signal(list, set)  # files, partial


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
        self._file_view.setItemDelegate(_FileDelegate(self._file_view))

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

    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._commands = commands
        self._file_model.set_commands(commands)
        self._hunk_diff.set_buses(queries, commands)
        if queries is None:
            self._file_model.reload([], set())
            self._hunk_diff.clear()

    def reload(self) -> None:
        queries = self._queries

        signals = _LoadSignals()
        signals.done.connect(self._on_reload_done)
        self._load_signals = signals  # prevent GC

        def _worker():
            files = queries.get_working_tree.execute()
            partial = _detect_partial(files)
            signals.done.emit(files, partial)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_reload_done(self, files: list[FileStatus], partial: set[str]) -> None:
        if self._queries is None:
            return
        self._file_model.reload(files, partial)
        self._hunk_diff.clear()

    def _on_file_selected(self, current, previous) -> None:
        if not current.isValid():
            return
        fs = self._file_model.data(current, Qt.UserRole)
        if fs is None:
            return
        self._hunk_diff.load_file(fs.path)

    def _on_stage_all(self) -> None:
        files = self._queries.get_working_tree.execute()
        partial = _detect_partial(files)
        paths = list({f.path for f in files if f.status != "staged"} | partial)
        if paths:
            self._commands.stage_files.execute(paths)
            self._on_files_changed()

    def _on_unstage_all(self) -> None:
        files = self._queries.get_working_tree.execute()
        partial = _detect_partial(files)
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

        queries = self._queries

        signals = _LoadSignals()
        signals.done.connect(lambda files, partial: self._on_files_changed_done(
            files, partial, selected_path))
        self._load_signals = signals  # prevent GC

        def _worker():
            files = queries.get_working_tree.execute()
            partial = _detect_partial(files)
            signals.done.emit(files, partial)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_files_changed_done(self, files: list[FileStatus], partial: set[str],
                               selected_path: str | None) -> None:
        if self._queries is None:
            return
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


def _detect_partial(files: list[FileStatus]) -> set[str]:
    """Detect files with partial staging (same path in both staged and unstaged)."""
    partial: set[str] = set()
    seen: set[str] = set()
    for f in files:
        if f.path in seen:
            partial.add(f.path)
        seen.add(f.path)
    return partial
