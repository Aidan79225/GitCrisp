from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QMessageBox,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from git_gui.domain.entities import WORKING_TREE_OID, Hunk, StagingState
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.theme import connect_widget
from git_gui.presentation.widgets.diff_block import (
    make_diff_formats,
    make_file_block,
    make_overflow_notice,
    make_syntax_formats,
)
from git_gui.presentation.widgets.hunk_view import add_hunk_view, hide_hunks_if_collapsed
from git_gui.presentation.widgets.shared_hscroll import SharedHScroll
from git_gui.presentation.widgets.viewport_block_loader import ViewportBlockLoader
from git_gui.resources import get_resource_path

# Resolved once, against the project root or the PyInstaller bundle rather than
# the working directory: a packaged GitCrisp starts wherever the user launched
# it from, and a relative path finds nothing there. The cost of getting that
# wrong is not a missing icon — Qt's "Cannot open file" warning reaches the
# message handler from inside the hunk block being built, and in a windowed
# build that handler had no stderr to write to, so the warning came back as an
# exception that aborted the diff render.
_CLOSE_ICON_PATH = str(get_resource_path("arts") / "ic_close.svg")

# Cap on how many file blocks the aggregate ("all files") diff view builds at
# once. Each block is a full QFrame subtree registered with the theme manager,
# so building one per changed file freezes the UI when the working tree holds
# thousands of changes. Above this cap only the first N files get a diff block;
# the rest stay reachable by selecting them in the file list (single-file mode
# is cheap). Chosen well above a typical review size but low enough that block
# construction stays imperceptible.
MAX_AGGREGATE_FILE_BLOCKS = 200

# Names each hunk's discard button, so a stage or discard can find them all.
_DISCARD_BUTTON_NAME = "discard_hunk"


class _LoadSignals(QObject):
    done = Signal(str, list, list, bool)  # path, staged_hunks, unstaged_hunks, is_untracked


class _DiffMapSignals(QObject):
    done = Signal(object, int)  # dict[str, dict[str, list[Hunk]]], blocks generation


class HunkDiffWidget(QWidget):
    hunk_toggled = Signal()
    discard_hunk_requested = Signal(str, str)  # path, hunk_header
    submodule_open_requested = Signal(str)  # emits the submodule path (relative)
    operation_failed = Signal(str)  # what failed and why, for the log panel

    def __init__(self, queries: QueryBus, commands: CommandBus, parent=None) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands
        self._current_path: str | None = None
        self._all_paths: list[str] | None = None  # None = single-file or empty mode
        self._submodule_paths: set[str] = set()
        # The all-files view's blocks by path, so a reload can find the height
        # each one had before it is rebuilt as a skeleton.
        self._aggregate_blocks: dict[str, QFrame] = {}
        # Bumped whenever the blocks are torn down. A diff map hands back the
        # generation it was asked for, so one meant for blocks that are gone,
        # after a repo switch or a newer load, is dropped.
        self._blocks_generation = 0

        # Lazy loading — initialized after scroll area is created (see below)
        self._loader: ViewportBlockLoader | None = None

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 8, 4, 4)
        self._scroll.setWidget(self._container)

        # One horizontal bar for every hunk, under the pane rather than inside
        # each of them — see SharedHScroll.
        self._hscroll = QScrollBar()
        self._hscroll_sync = SharedHScroll(self._hscroll, self._container, self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)
        outer.addWidget(self._hscroll, 0)

        # Diff render formats — line backgrounds plus Pygments syntax colours and
        # word-level overlays, matching the commit-detail diff view. Rebuilt on
        # theme change so blocks realised after a theme switch use fresh colours.
        self._formats = make_diff_formats()
        self._syntax_formats = make_syntax_formats()
        connect_widget(self, rebuild=self._on_theme_changed)

        self._loader = ViewportBlockLoader(self._scroll, self._realize_block_from_loader)

    def _on_theme_changed(self) -> None:
        self._formats = make_diff_formats()
        self._syntax_formats = make_syntax_formats()

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
        """Load and display hunks for the given paths with a bordered file block per file.

        To keep the UI responsive when the working tree holds a very large
        number of changes, at most ``MAX_AGGREGATE_FILE_BLOCKS`` diff blocks are
        built; any remainder is summarised by a trailing notice. Every file
        stays inspectable via the file list (single-file mode).
        """
        self._current_path = None
        self._all_paths = list(paths)
        last_heights = self._aggregate_block_heights()
        if not paths:
            self._clear_layout()
            return

        self._refresh_submodule_paths()
        self._clear_layout()

        from git_gui.presentation.widgets.diff_block import make_skeleton_container

        shown = paths[:MAX_AGGREGATE_FILE_BLOCKS]
        hidden = len(paths) - len(shown)

        block_refs = []
        for path in shown:
            frame, inner = self._make_file_block(path)
            # A skeleton is far shorter than the block it stands for. Holding
            # the block's last height until it is realised keeps the content
            # above the user's place the same height, so the unchanged scroll
            # value still shows the same file after a stage or discard.
            frame.setMinimumHeight(last_heights.get(path, 0))
            self._aggregate_blocks[path] = frame
            skeleton = make_skeleton_container()
            inner.addWidget(skeleton)
            self._layout.addWidget(frame)
            spacer = QSpacerItem(0, 8, QSizePolicy.Minimum, QSizePolicy.Fixed)
            self._layout.addItem(spacer)
            block_refs.append((path, frame, inner, skeleton))

        if hidden > 0:
            self._layout.addWidget(make_overflow_notice(hidden))

        self._layout.addStretch()
        self._loader.set_blocks(block_refs)

        queries = self._queries
        generation = self._blocks_generation
        signals = _DiffMapSignals()
        signals.done.connect(self._on_diff_map_loaded)
        self._load_all_signals = signals  # prevent GC

        def _worker():
            try:
                # Only compute diffs for the paths we actually render — computing
                # hunks for every changed file is what makes large working trees
                # hang, even off the UI thread.
                result = queries.get_working_tree_diff_map.execute(shown)
            except Exception:
                result = {}
            signals.done.emit(result, generation)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_diff_map_loaded(self, diff_map: dict, generation: int) -> None:
        if generation == self._blocks_generation:
            self._loader.set_diff_map(diff_map)

    def _aggregate_block_heights(self) -> dict[str, int]:
        """Each all-files block's height: its content's, or the one it still holds.

        Read from the size hint rather than the geometry, which a block not
        yet laid out does not have.
        """
        return {
            path: max(frame.sizeHint().height(), frame.minimumHeight())
            for path, frame in self._aggregate_blocks.items()
        }

    def _sync_hscroll(self) -> None:
        """Re-measure the shared horizontal bar once the layout has settled.

        Deferred: an editor added this turn has no width yet, so its scroll
        range reads as zero until Qt has laid it out. Bound to this pane's
        lifetime, so a re-measure still pending when the pane is destroyed is
        dropped instead of reaching into the destroyed container.
        """
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self, self._hscroll_sync.refresh)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # A wider pane means less of the content is out of reach.
        self._hscroll_sync.refresh()

    def clear(self) -> None:
        self._current_path = None
        self._all_paths = None
        self._clear_layout()
        self._sync_hscroll()

    def refresh_view(self) -> None:
        """Redraw after the unified/side-by-side choice changed, keeping the
        file selection: one file stays one file, and the aggregate view stays
        aggregate."""
        if self._current_path is not None:
            self.load_file(self._current_path)
        elif self._all_paths is not None:
            self.load_all_files(self._all_paths)

    def _fetch_and_render(self) -> None:
        if self._current_path is None:
            return
        path = self._current_path
        queries = self._queries

        signals = _LoadSignals()
        signals.done.connect(self._on_load_done)
        self._load_signals = signals  # prevent GC

        def _worker():
            try:
                staged_hunks = queries.get_staged_diff.execute(path)
            except Exception:
                staged_hunks = []
            try:
                unstaged_hunks = queries.get_file_diff.execute(WORKING_TREE_OID, path)
            except Exception:
                unstaged_hunks = []
            is_untracked = (
                not staged_hunks
                and bool(unstaged_hunks)
                and unstaged_hunks[0].header.startswith("@@ -0,0")
            )
            signals.done.emit(path, staged_hunks, unstaged_hunks, is_untracked)

        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_submodule_paths(self) -> None:
        if self._queries is None:
            self._submodule_paths = set()
            return
        try:
            self._submodule_paths = {s.path for s in self._queries.list_submodules.execute()}
        except Exception:
            self._submodule_paths = set()

    def _make_file_block(self, path: str):
        on_click = (
            (lambda p=path: self.submodule_open_requested.emit(p))
            if path in self._submodule_paths
            else None
        )
        return make_file_block(
            path,
            on_header_clicked=on_click,
            on_state_changed=lambda _expanded: self._loader.check_viewport(),
        )

    def _on_load_done(
        self, path: str, staged_hunks: list[Hunk], unstaged_hunks: list[Hunk], is_untracked: bool
    ) -> None:
        if path != self._current_path:
            return
        self._refresh_submodule_paths()
        self._clear_layout()

        frame, inner = self._make_file_block(path)
        for hunk in staged_hunks:
            self._add_hunk_block(
                hunk, is_staged=True, is_untracked=False, path=path, parent_layout=inner
            )
        for hunk in unstaged_hunks:
            self._add_hunk_block(
                hunk, is_staged=False, is_untracked=is_untracked, path=path, parent_layout=inner
            )

        self._layout.addWidget(frame)
        self._layout.addStretch()
        self._sync_hscroll()

    def _realize_block_from_loader(self, path: str, inner, skeleton, entry) -> None:
        """Callback for ViewportBlockLoader — replace skeleton with staged/unstaged hunks."""
        staged_hunks = entry.get(StagingState.STAGED, [])
        unstaged_hunks = entry.get(StagingState.UNSTAGED, [])
        is_untracked = (
            not staged_hunks
            and bool(unstaged_hunks)
            and unstaged_hunks[0].header.startswith("@@ -0,0")
        )
        if skeleton is not None:
            inner.removeWidget(skeleton)
            skeleton.deleteLater()
        inner.parentWidget().setMinimumHeight(0)  # the real content now sets it
        for hunk in staged_hunks:
            self._add_hunk_block(
                hunk, is_staged=True, is_untracked=False, path=path, parent_layout=inner
            )
        for hunk in unstaged_hunks:
            self._add_hunk_block(
                hunk, is_staged=False, is_untracked=is_untracked, path=path, parent_layout=inner
            )
        hide_hunks_if_collapsed(inner)
        self._sync_hscroll()

    def _render_sync(self) -> None:
        """Post-action refresh for single-file mode."""
        self._refresh_submodule_paths()
        self._clear_layout()
        if self._current_path is None:
            return
        path = self._current_path
        staged_hunks = self._queries.get_staged_diff.execute(path)
        unstaged_hunks = self._queries.get_file_diff.execute(WORKING_TREE_OID, path)
        is_untracked = (
            not staged_hunks
            and bool(unstaged_hunks)
            and unstaged_hunks[0].header.startswith("@@ -0,0")
        )

        frame, inner = self._make_file_block(path)
        for hunk in staged_hunks:
            self._add_hunk_block(
                hunk, is_staged=True, is_untracked=False, path=path, parent_layout=inner
            )
        for hunk in unstaged_hunks:
            self._add_hunk_block(
                hunk, is_staged=False, is_untracked=is_untracked, path=path, parent_layout=inner
            )

        self._layout.addWidget(frame)
        self._layout.addStretch()
        self._sync_hscroll()

    def _redraw_after_command(self) -> None:
        """Redraw from the index after a stage, unstage or discard.

        Only the single-file view redraws itself. The all-files view is left
        to its owner, which reloads it on hunk_toggled / discard_hunk_requested
        with the new list of changed files, a list only the owner knows: a
        discard can take a file out of it. Reloading here as well rebuilt
        every block and queried every diff twice per click.

        Until that reload rebuilds them, the all-files view's stage and
        discard controls are disabled: the command may have moved the line
        numbers of the hunks below it, so their headers no longer name a hunk
        the index has.
        """
        if self._all_paths is None:
            self._render_sync()
        else:
            self._disable_hunk_controls()

    def _disable_hunk_controls(self) -> None:
        # Only the controls: disabling the container would grey every diff
        # line on screen until the reload lands, a flash on each click.
        controls = self._container.findChildren(QCheckBox) + self._container.findChildren(
            QToolButton, _DISCARD_BUTTON_NAME
        )
        for control in controls:
            control.setEnabled(False)

    def _add_hunk_block(
        self,
        hunk: Hunk,
        is_staged: bool,
        is_untracked: bool,
        path: str | None = None,
        parent_layout: QVBoxLayout | None = None,
    ) -> None:
        # Use explicitly passed path, fall back to self._current_path for backward compat
        if path is None:
            path = self._current_path
        # Use explicitly passed layout, fall back to self._layout for backward compat
        target_layout = parent_layout if parent_layout is not None else self._layout

        header = hunk.header

        checkbox = QCheckBox()
        checkbox.setChecked(is_staged)
        checkbox.toggled.connect(
            lambda checked, p=path, h=header, u=is_untracked: self._on_hunk_toggled(
                p, h, checked, u
            )
        )

        extra_right: list = []
        if not is_staged:
            # Whole-file add (`@@ -0,0 ...`) or whole-file delete (`+0,0 @@`)
            # is best handled by discard_file (full reset), since `git apply
            # --reverse` only touches the working tree and leaves the index
            # in a confusing state.
            is_whole_file = header.startswith("@@ -0,0") or "+0,0 @@" in header
            x_btn = QToolButton()
            x_btn.setObjectName(_DISCARD_BUTTON_NAME)
            x_btn.setIcon(QIcon(_CLOSE_ICON_PATH))
            x_btn.setIconSize(QSize(16, 16))
            x_btn.setFixedSize(22, 22)
            x_btn.setToolTip("Discard this file" if is_whole_file else "Discard this hunk")
            x_btn.setAccessibleName(x_btn.toolTip())
            x_btn.setAutoRaise(True)
            x_btn.clicked.connect(
                lambda _=False, p=path, h=header, w=is_whole_file: (
                    self._on_discard_file_clicked(p) if w else self._on_discard_hunk_clicked(p, h)
                )
            )
            extra_right = [x_btn]

        on_click = (
            (lambda p=path: self.submodule_open_requested.emit(p))
            if path in self._submodule_paths
            else None
        )
        add_hunk_view(
            target_layout,
            hunk,
            self._formats,
            extra_left_widgets=[checkbox],
            extra_right_widgets=extra_right,
            on_header_clicked=on_click,
            syntax_formats=self._syntax_formats,
            filename=path,
        )

    def _on_hunk_toggled(
        self, path: str, hunk_header: str, checked: bool, is_untracked: bool = False
    ) -> None:
        verb = "Stage" if checked else "Unstage"
        self._run_command(
            f"{verb} {path}",
            lambda: self._stage_or_unstage(path, hunk_header, checked, is_untracked),
        )
        self._redraw_after_command()
        self.hunk_toggled.emit()

    def _stage_or_unstage(
        self, path: str, hunk_header: str, checked: bool, is_untracked: bool
    ) -> None:
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

    def _run_command(self, action: str, command: Callable[[], None]) -> None:
        """Run a staging or discard command, reporting a failure to the user.

        A failure must not escape the Qt slot: it would skip the redraw that
        puts the checkbox back in step with the index, and reach nothing but
        the log file, so the user would commit believing the hunk was staged.
        """
        try:
            command()
        except Exception as e:
            self.operation_failed.emit(f"{action} failed: {e}")

    def _on_discard_file_clicked(self, path: str) -> None:
        reply = QMessageBox.question(
            self,
            "Discard file",
            f"Discard all changes to {path}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._run_command(f"Discard {path}", lambda: self._commands.discard_file.execute(path))
        self.discard_hunk_requested.emit(path, "")

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
        self._run_command(
            f"Discard hunk in {path}",
            lambda: self._commands.discard_hunk.execute(path, hunk_header),
        )
        self._redraw_after_command()
        self.discard_hunk_requested.emit(path, hunk_header)

    def _clear_layout(self) -> None:
        self._aggregate_blocks = {}
        self._blocks_generation += 1
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if self._loader:
            self._loader.clear()
