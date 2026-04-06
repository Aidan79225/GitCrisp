# git_gui/presentation/widgets/hunk_diff.py
from __future__ import annotations
import threading
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QMessageBox, QScrollArea,
    QSpacerItem, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import Hunk
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.presentation.widgets.diff_block import (
    make_file_block, make_diff_formats, add_hunk_widget,
)


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
        self._formats = make_diff_formats()

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
        """Load and display hunks for all given paths with a bordered file block per file."""
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

    def _make_file_block(self, path: str):
        """Return a bordered QFrame file block and its inner layout."""
        return make_file_block(path)

    def _on_load_done(self, path: str, staged_hunks: list[Hunk],
                      unstaged_hunks: list[Hunk], is_untracked: bool) -> None:
        if path != self._current_path:
            return
        self._clear_layout()

        frame, inner = self._make_file_block(path)
        for hunk in staged_hunks:
            self._add_hunk_block(hunk, is_staged=True, is_untracked=False,
                                 path=path, parent_layout=inner)
        for hunk in unstaged_hunks:
            self._add_hunk_block(hunk, is_staged=False, is_untracked=is_untracked,
                                 path=path, parent_layout=inner)

        self._layout.addWidget(frame)
        self._layout.addStretch()

    def _on_load_all_done(self, results: list) -> None:
        # Check we're still in all-files mode and paths haven't changed
        if self._all_paths is None:
            return
        self._clear_layout()
        for path, staged_hunks, unstaged_hunks, is_untracked in results:
            frame, inner = self._make_file_block(path)

            for hunk in staged_hunks:
                self._add_hunk_block(hunk, is_staged=True, is_untracked=False,
                                     path=path, parent_layout=inner)
            for hunk in unstaged_hunks:
                self._add_hunk_block(hunk, is_staged=False, is_untracked=is_untracked,
                                     path=path, parent_layout=inner)

            self._layout.addWidget(frame)

            # Small vertical spacer between file blocks
            spacer = QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Fixed)
            self._layout.addItem(spacer)

        self._layout.addStretch()

    def _render_sync(self) -> None:
        """Post-action refresh for single-file mode."""
        self._clear_layout()
        if self._current_path is None:
            return
        path = self._current_path
        staged_hunks = self._queries.get_staged_diff.execute(path)
        unstaged_hunks = self._queries.get_file_diff.execute(
            WORKING_TREE_OID, path
        )
        is_untracked = (
            not staged_hunks
            and bool(unstaged_hunks)
            and unstaged_hunks[0].header.startswith("@@ -0,0")
        )

        frame, inner = self._make_file_block(path)
        for hunk in staged_hunks:
            self._add_hunk_block(hunk, is_staged=True, is_untracked=False,
                                 path=path, parent_layout=inner)
        for hunk in unstaged_hunks:
            self._add_hunk_block(hunk, is_staged=False, is_untracked=is_untracked,
                                 path=path, parent_layout=inner)

        self._layout.addWidget(frame)
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

            frame, inner = self._make_file_block(path)
            for hunk in staged_hunks:
                self._add_hunk_block(hunk, is_staged=True, is_untracked=False,
                                     path=path, parent_layout=inner)
            for hunk in unstaged_hunks:
                self._add_hunk_block(hunk, is_staged=False, is_untracked=is_untracked,
                                     path=path, parent_layout=inner)

            self._layout.addWidget(frame)

            spacer = QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Fixed)
            self._layout.addItem(spacer)

        self._layout.addStretch()

    def _add_hunk_block(self, hunk: Hunk, is_staged: bool, is_untracked: bool,
                        path: str | None = None,
                        parent_layout: QVBoxLayout | None = None) -> None:
        # Use explicitly passed path, fall back to self._current_path for backward compat
        if path is None:
            path = self._current_path
        # Use explicitly passed layout, fall back to self._layout for backward compat
        target_layout = parent_layout if parent_layout is not None else self._layout

        header = hunk.header

        checkbox = QCheckBox()
        checkbox.setChecked(is_staged)
        checkbox.toggled.connect(
            lambda checked, p=path, h=header, u=is_untracked:
                self._on_hunk_toggled(p, h, checked, u)
        )

        extra_right: list = []
        if not is_staged and not is_untracked:
            x_btn = QToolButton()
            x_btn.setIcon(QIcon("arts/ic_close.svg"))
            x_btn.setIconSize(QSize(16, 16))
            x_btn.setFixedSize(22, 22)
            x_btn.setToolTip("Discard this hunk")
            x_btn.setAutoRaise(True)
            x_btn.clicked.connect(
                lambda _=False, p=path, h=header: self._on_discard_hunk_clicked(p, h)
            )
            extra_right = [x_btn]

        add_hunk_widget(
            target_layout,
            hunk,
            self._formats,
            extra_left_widgets=[checkbox],
            extra_right_widgets=extra_right,
        )

    def _on_hunk_toggled(self, path: str, hunk_header: str, checked: bool,
                         is_untracked: bool = False) -> None:
        # Whole-file add (untracked → stage, or staged-add → unstage):
        # the synthesised "@@ -0,0 +1,N @@" hunk can't be processed by
        # `git apply [--cached] [--reverse]`, so route to stage/unstage_files.
        if is_untracked or hunk_header.startswith("@@ -0,0"):
            if checked:
                self._commands.stage_files.execute([path])
            else:
                self._commands.unstage_files.execute([path])
        elif checked:
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
