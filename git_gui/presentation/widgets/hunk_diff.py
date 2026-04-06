# git_gui/presentation/widgets/hunk_diff.py
from __future__ import annotations
import threading
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QScrollArea,
    QSpacerItem, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import Hunk
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.domain.entities import WORKING_TREE_OID


class _LoadSignals(QObject):
    done = Signal(str, list, list, bool)  # path, staged_hunks, unstaged_hunks, is_untracked


class _LoadAllSignals(QObject):
    done = Signal(list)  # list of (path, staged_hunks, unstaged_hunks, is_untracked) tuples


class HunkDiffWidget(QWidget):
    hunk_toggled = Signal()
    discard_hunk_requested = Signal(str, str)  # path, hunk_header

    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands
        self._current_path: str | None = None
        self._all_paths: list[str] | None = None  # None = single-file or empty mode

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
        self._all_paths = None
        self._fetch_and_render()

    def load_all_files(self, paths: list[str]) -> None:
        """Load and display hunks for all given paths with a bold header per file."""
        self._current_path = None
        self._all_paths = list(paths)
        if not paths:
            self._clear_layout()
            return

        queries = self._queries
        all_paths = self._all_paths

        signals = _LoadAllSignals()
        signals.done.connect(self._on_load_all_done)
        self._load_all_signals = signals  # prevent GC

        def _worker():
            results = []
            for path in all_paths:
                staged_hunks = queries.get_staged_diff.execute(path)
                unstaged_hunks = queries.get_file_diff.execute(WORKING_TREE_OID, path)
                is_untracked = (
                    not staged_hunks
                    and bool(unstaged_hunks)
                    and unstaged_hunks[0].header.startswith("@@ -0,0")
                )
                results.append((path, staged_hunks, unstaged_hunks, is_untracked))
            signals.done.emit(results)

        threading.Thread(target=_worker, daemon=True).start()

    def clear(self) -> None:
        self._current_path = None
        self._all_paths = None
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
            # untracked when there is content in unstaged but nothing staged AND no header has @@ -<n>
            is_untracked = (
                not staged_hunks
                and bool(unstaged_hunks)
                and unstaged_hunks[0].header.startswith("@@ -0,0")
            )
            signals.done.emit(path, staged_hunks, unstaged_hunks, is_untracked)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_load_done(self, path: str, staged_hunks: list[Hunk],
                      unstaged_hunks: list[Hunk], is_untracked: bool) -> None:
        if path != self._current_path:
            return
        self._clear_layout()
        for hunk in staged_hunks:
            self._add_hunk_block(hunk, is_staged=True, is_untracked=False, path=path)
        for hunk in unstaged_hunks:
            self._add_hunk_block(hunk, is_staged=False, is_untracked=is_untracked, path=path)
        self._layout.addStretch()

    def _on_load_all_done(self, results: list) -> None:
        # Check we're still in all-files mode and paths haven't changed
        if self._all_paths is None:
            return
        self._clear_layout()
        for path, staged_hunks, unstaged_hunks, is_untracked in results:
            # Bold file-path header label
            header_label = QLabel(f"\U0001f4c4 {path}")
            header_font = header_label.font()
            header_font.setBold(True)
            header_label.setFont(header_font)
            self._layout.addWidget(header_label)

            for hunk in staged_hunks:
                self._add_hunk_block(hunk, is_staged=True, is_untracked=False, path=path)
            for hunk in unstaged_hunks:
                self._add_hunk_block(hunk, is_staged=False, is_untracked=is_untracked, path=path)

            # Small vertical spacer after each file
            spacer = QSpacerItem(0, 12, QSizePolicy.Minimum, QSizePolicy.Fixed)
            self._layout.addItem(spacer)

        self._layout.addStretch()

    def _render_sync(self) -> None:
        """Post-action refresh for single-file mode."""
        self._clear_layout()
        if self._current_path is None:
            return
        staged_hunks = self._queries.get_staged_diff.execute(self._current_path)
        unstaged_hunks = self._queries.get_file_diff.execute(
            WORKING_TREE_OID, self._current_path
        )
        is_untracked = (
            not staged_hunks
            and bool(unstaged_hunks)
            and unstaged_hunks[0].header.startswith("@@ -0,0")
        )
        for hunk in staged_hunks:
            self._add_hunk_block(hunk, is_staged=True, is_untracked=False,
                                 path=self._current_path)
        for hunk in unstaged_hunks:
            self._add_hunk_block(hunk, is_staged=False, is_untracked=is_untracked,
                                 path=self._current_path)
        self._layout.addStretch()

    def _render_all_sync(self) -> None:
        """Post-action refresh for all-files mode."""
        if self._all_paths is None:
            return
        self._clear_layout()
        for path in self._all_paths:
            staged_hunks = self._queries.get_staged_diff.execute(path)
            unstaged_hunks = self._queries.get_file_diff.execute(WORKING_TREE_OID, path)
            is_untracked = (
                not staged_hunks
                and bool(unstaged_hunks)
                and unstaged_hunks[0].header.startswith("@@ -0,0")
            )

            header_label = QLabel(f"\U0001f4c4 {path}")
            header_font = header_label.font()
            header_font.setBold(True)
            header_label.setFont(header_font)
            self._layout.addWidget(header_label)

            for hunk in staged_hunks:
                self._add_hunk_block(hunk, is_staged=True, is_untracked=False, path=path)
            for hunk in unstaged_hunks:
                self._add_hunk_block(hunk, is_staged=False, is_untracked=is_untracked,
                                     path=path)

            spacer = QSpacerItem(0, 12, QSizePolicy.Minimum, QSizePolicy.Fixed)
            self._layout.addItem(spacer)

        self._layout.addStretch()

    def _add_hunk_block(self, hunk: Hunk, is_staged: bool, is_untracked: bool,
                        path: str | None = None) -> None:
        # Use explicitly passed path, fall back to self._current_path for backward compat
        if path is None:
            path = self._current_path

        checkbox = QCheckBox(hunk.header.strip())
        checkbox.setChecked(is_staged)

        header = hunk.header
        checkbox.toggled.connect(
            lambda checked, p=path, h=header: self._on_hunk_toggled(p, h, checked)
        )

        # Header row: checkbox on the left, optional X button on the right
        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(checkbox)
        header_layout.addStretch()
        if not is_staged and not is_untracked:
            x_btn = QToolButton()
            x_btn.setIcon(QIcon("arts/ic_close.svg"))
            x_btn.setToolTip("Discard this hunk")
            x_btn.setAutoRaise(True)
            x_btn.clicked.connect(
                lambda _=False, p=path, h=header: self._on_discard_hunk_clicked(p, h)
            )
            header_layout.addWidget(x_btn)

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

        line_height = editor.fontMetrics().lineSpacing()
        margins = editor.contentsMargins()
        doc_margin = editor.document().documentMargin() * 2
        total_height = int(len(hunk.lines) * line_height + doc_margin + margins.top() + margins.bottom() + 4)
        editor.setFixedHeight(total_height)

        self._layout.addWidget(header_row)
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
        if self._all_paths is not None:
            self._render_all_sync()
        else:
            self._render_sync()
        self.hunk_toggled.emit()

    def _on_discard_hunk_clicked(self, path: str, hunk_header: str) -> None:
        reply = QMessageBox.question(
            self,
            "Discard hunk",
            "Discard this hunk? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._commands.discard_hunk.execute(path, hunk_header)
        if self._all_paths is not None:
            self._render_all_sync()
        else:
            self._render_sync()
        self.discard_hunk_requested.emit(path, hunk_header)

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
