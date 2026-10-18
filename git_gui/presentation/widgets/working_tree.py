from __future__ import annotations

import logging
import os
import re
import threading

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QBrush, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from git_gui.domain.entities import FileStatus, RepoState, StagingState
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.theme import ColorRole, connect_widget, get_theme_manager
from git_gui.presentation.widgets.check_indicator import CheckIndicatorDelegate
from git_gui.presentation.widgets.file_list_view import (
    BADGE_LABEL,
    UNKNOWN_LABEL,
    badge_kind,
)
from git_gui.presentation.widgets.file_list_view import FileListView as _FileListView
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget
from git_gui.presentation.widgets.working_tree_model import WorkingTreeModel

logger = logging.getLogger(__name__)

_BADGE_SIZE = 20
# Qt knows nothing about the badge, so the row's text is padded to leave a gap
# the badge is then painted into, clear of the check indicator.
_BADGE_TEXT_RESERVATION = "          "
_BADGE_LEFT_INSET = 30

# Characters a .gitignore line reads as glob syntax or as an escape.
_GITIGNORE_SPECIALS = re.compile(r"[\\*?\[]")

# While one of these runs, Commit continues it rather than creating a commit.
# A detached HEAD is not among them: committing there is an ordinary commit.
_OPERATIONS_IN_PROGRESS = frozenset(
    {RepoState.MERGING, RepoState.REBASING, RepoState.CHERRY_PICKING, RepoState.REVERTING}
)


class _FileDelegate(CheckIndicatorDelegate):
    """Adds a delta badge between the check indicator and filename."""

    def initStyleOption(self, option: QStyleOptionViewItem, index) -> None:
        super().initStyleOption(option, index)
        option.text = _BADGE_TEXT_RESERVATION + (option.text or "")

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect
        kind = badge_kind(index.data(Qt.UserRole))
        # A paint() that raises takes the whole view down with it.
        label = BADGE_LABEL.get(kind, UNKNOWN_LABEL)

        badge_x = rect.left() + _BADGE_LEFT_INSET
        badge_y = rect.top() + (rect.height() - _BADGE_SIZE) // 2
        badge_rect = QRect(badge_x, badge_y, _BADGE_SIZE, _BADGE_SIZE)
        painter.setBrush(QBrush(get_theme_manager().current.colors.status_color(kind)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(badge_rect, 3, 3)
        painter.setPen(get_theme_manager().current.colors.as_qcolor(ColorRole.ON_BADGE))
        painter.drawText(badge_rect, Qt.AlignCenter, label)

        painter.restore()


class _LoadSignals(QObject):
    done = Signal(list, set, int)  # files, partial, load generation
    failed = Signal(str, int)  # error reason, load generation


class WorkingTreeWidget(QWidget):
    reload_requested = Signal()
    commit_completed = Signal(str)  # emits first line of commit message
    # Error reason, for a commit or any other change made from this panel;
    # MainWindow shows it in the operations log.
    commit_failed = Signal(str)
    load_failed = Signal(str)  # why the changed files could not be listed
    working_tree_empty = Signal()  # emitted when reload finds no changes
    submodule_open_requested = Signal(str)  # forwarded from inner HunkDiffWidget
    file_history_requested = Signal(str)  # repo-relative path
    blame_requested = Signal(str, object)  # path, revision (None = HEAD)
    merge_abort_requested = Signal()
    rebase_abort_requested = Signal()
    merge_continue_requested = Signal(str)  # commit message
    rebase_continue_requested = Signal(str)  # commit message
    cherry_pick_abort_requested = Signal()
    revert_abort_requested = Signal()
    cherry_pick_continue_requested = Signal()
    revert_continue_requested = Signal()

    def __init__(
        self, queries: QueryBus, commands: CommandBus, repo_path: str | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands
        self._repo_path = repo_path
        # Bumped on every repo switch and every reload. A load hands its
        # generation back with its result, so one that finishes after the
        # switch, or after a newer load, is recognised as stale and dropped.
        self._load_generation = 0

        # ── Conflict banner (hidden by default) ─────────────────────────
        self._conflict_banner = QWidget()
        banner_layout = QHBoxLayout(self._conflict_banner)
        banner_layout.setContentsMargins(8, 6, 8, 6)
        self._banner_label = QLabel("")
        self._banner_label.setStyleSheet("font-weight: bold;")
        self._btn_abort = QPushButton("Abort")
        banner_layout.addWidget(self._banner_label, 1)
        banner_layout.addWidget(self._btn_abort)
        self._restyle_banner()
        self._conflict_banner.setVisible(False)

        # ── Row 1: commit toolbar ────────────────────────────────────────────
        self._msg_edit = QPlainTextEdit()
        self._msg_edit.setPlaceholderText("Commit message...")
        self._msg_edit.setAccessibleName("Commit message")
        self._msg_edit.setMaximumHeight(80)

        self._btn_stage_all = QPushButton("Stage All")
        self._btn_unstage_all = QPushButton("Unstage All")
        self._btn_commit = QPushButton("Commit")
        # Ctrl+Enter (Cmd+Enter on macOS) commits from anywhere in this panel,
        # most usefully straight from the message editor, where plain Enter
        # has to stay a newline.
        self._commit_shortcuts = [
            QShortcut(QKeySequence(seq), self, context=Qt.WidgetWithChildrenShortcut)
            for seq in ("Ctrl+Return", "Ctrl+Enter")
        ]
        self._btn_commit.setToolTip(
            f"Commit ({self._commit_shortcuts[0].key().toString(QKeySequence.NativeText)})"
        )
        self._chk_amend = QCheckBox("Amend last commit")
        self._chk_amend.setToolTip(
            "Replace the last commit instead of creating a new one.\n"
            "Rewrites history — avoid on commits you have already pushed."
        )
        # Draft the user was typing before ticking Amend, restored on untick.
        self._draft_msg = ""

        btn_layout = QVBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addWidget(self._btn_stage_all)
        btn_layout.addWidget(self._btn_unstage_all)
        btn_layout.addWidget(self._btn_commit)
        btn_layout.addWidget(self._chk_amend)

        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(4, 4, 4, 4)
        toolbar_layout.addWidget(self._msg_edit, 1)
        toolbar_layout.addLayout(btn_layout)

        # ── Row 2: file list ─────────────────────────────────────────────────
        self._file_view = _FileListView()
        self._file_view.setAccessibleName("Changed files")
        self._file_view.setEditTriggers(QListView.NoEditTriggers)
        self._file_view.setItemDelegate(_FileDelegate(self._file_view))

        self._file_model = WorkingTreeModel(commands, self)
        self._file_view.setModel(self._file_model)
        self._file_view.selectionModel().currentChanged.connect(self._on_file_selected)
        self._file_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._file_view.customContextMenuRequested.connect(self._on_file_context_menu)
        self._file_view.deselected.connect(self._on_file_deselected)

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
        layout.addWidget(self._conflict_banner)
        layout.addWidget(splitter)

        # ── Signals ──────────────────────────────────────────────────────────
        self._btn_stage_all.clicked.connect(self._on_stage_all)
        self._btn_unstage_all.clicked.connect(self._on_unstage_all)
        self._btn_commit.clicked.connect(self._on_commit)
        for shortcut in self._commit_shortcuts:
            shortcut.activated.connect(self._on_commit_shortcut)
        self._chk_amend.toggled.connect(self._on_amend_toggled)
        self._file_model.files_changed.connect(self._on_files_changed)
        self._file_model.operation_failed.connect(self.commit_failed)
        self._hunk_diff.hunk_toggled.connect(self._on_files_changed)
        self._hunk_diff.discard_hunk_requested.connect(lambda *_: self._on_files_changed())
        self._hunk_diff.operation_failed.connect(self.commit_failed)
        self._hunk_diff.submodule_open_requested.connect(self.submodule_open_requested)
        self._btn_abort.clicked.connect(self._on_abort_clicked)

        connect_widget(self, rebuild=self._restyle_banner)

    def _restyle_banner(self) -> None:
        # No selector: the label and the Abort button take the banner's
        # colours, rather than a palette that was never chosen to sit on it.
        c = get_theme_manager().current.colors
        self._conflict_banner.setStyleSheet(
            f"background-color: {c.error}; color: {c.on_error}; border: none; padding: 2px;"
        )

    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._commands = commands
        # Amend, the message and any merge or rebase in progress all belong to
        # the repo being left; carried over, Commit would act on them here.
        self._untick_amend()
        self._draft_msg = ""
        self._msg_edit.clear()
        self.update_conflict_banner(RepoState.CLEAN)
        self._file_model.set_commands(commands)
        self._hunk_diff.set_buses(queries, commands)
        # The old repo's list would stage its paths through the new repo's
        # commands, so it goes, along with any status still on its way.
        self._load_generation += 1
        self._file_model.reload([], set())
        self._hunk_diff.clear()

    def set_repo_path(self, path: str | None) -> None:
        """Update the active repo path used by _ignore_file and any other
        path-sensitive helper. Called on repo switch by the composite."""
        self._repo_path = path

    def refresh_diff_view(self) -> None:
        self._hunk_diff.refresh_view()

    def reload(self) -> None:
        """Re-read the working tree, keeping the selected file selected.

        The change detector calls this after every index write, including a
        stage made from this panel, so a reload that dropped the selection
        would throw the user back to the all-files view after each one.
        """
        queries = self._queries
        if queries is None:
            return
        self._load_generation += 1
        generation = self._load_generation

        signals = _LoadSignals()
        signals.done.connect(self._on_reload_done)
        signals.failed.connect(self._on_reload_failed)
        self._load_signals = signals  # prevent GC

        def _worker():
            try:
                files, partial = _deduplicate(queries.get_working_tree.execute())
            except Exception as e:
                logger.warning("Working tree reload failed: %s", e)
                signals.failed.emit(str(e), generation)
                return
            signals.done.emit(files, partial, generation)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_reload_failed(self, message: str, generation: int) -> None:
        if self._queries is None or generation != self._load_generation:
            return
        # Left on screen, the old files stay offered for staging in a repo
        # that may no longer have them, deleted from a terminal for instance.
        self._file_model.reload([], set())
        self._hunk_diff.clear()
        self.load_failed.emit(message)

    def _on_reload_done(self, files: list[FileStatus], partial: set[str], generation: int) -> None:
        if self._queries is None or generation != self._load_generation:
            return
        selected_path = self._selected_path()
        files = _conflicts_first(files)
        self._file_model.reload(files, partial)
        if not files:
            self._hunk_diff.clear()
            self.working_tree_empty.emit()
        elif not (selected_path and self._reselect(selected_path)):
            self._hunk_diff.load_all_files([f.path for f in files])

    def _selected_path(self) -> str | None:
        fs = self._file_model.data(self._file_view.currentIndex(), Qt.UserRole)
        return fs.path if fs else None

    def _reselect(self, path: str) -> bool:
        """Select *path* again after a refill; False when it is no longer listed."""
        for row in range(self._file_model.rowCount()):
            index = self._file_model.index(row)
            fs = self._file_model.data(index, Qt.UserRole)
            if fs and fs.path == path:
                # The refill reset the model, which cleared the current index,
                # so this always emits currentChanged: _on_file_selected loads
                # the diff, and a load here as well would build it twice.
                self._file_view.setCurrentIndex(index)
                return True
        return False

    def _on_file_selected(self, current, previous) -> None:
        if not current.isValid():
            return
        fs = self._file_model.data(current, Qt.UserRole)
        if fs is None:
            return
        self._hunk_diff.load_file(fs.path)

    def _on_file_deselected(self) -> None:
        """Switch diff panel back to all-files view when user deselects current row."""
        files = [
            self._file_model.data(self._file_model.index(row), Qt.UserRole)
            for row in range(self._file_model.rowCount())
        ]
        paths = [f.path for f in files if f is not None]
        if paths:
            self._hunk_diff.load_all_files(paths)
        else:
            self._hunk_diff.clear()

    def _on_file_context_menu(self, pos) -> None:
        index = self._file_view.indexAt(pos)
        if not index.isValid():
            return
        fs = self._file_model.data(index, Qt.UserRole)
        if fs is None:
            return
        menu = QMenu(self._file_view)
        history_action = menu.addAction("Show file history")
        blame_action = menu.addAction("Blame this file")
        menu.addSeparator()
        discard_action = menu.addAction("Discard changes")
        ignore_action = menu.addAction("Add to .gitignore")
        chosen = menu.exec(self._file_view.viewport().mapToGlobal(pos))
        if chosen is history_action:
            self.file_history_requested.emit(fs.path)
        elif chosen is blame_action:
            # Working-tree files blame HEAD — the last committed state.
            self.blame_requested.emit(fs.path, None)
        elif chosen is discard_action:
            self._discard_file(fs.path)
        elif chosen is ignore_action:
            self._ignore_file(fs.path)

    def _discard_file(self, path: str) -> None:
        reply = QMessageBox.question(
            self,
            "Discard changes",
            f"Discard all changes to {path}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self._commands.discard_file.execute(path)
        except Exception as e:
            self.commit_failed.emit(f"Discard failed for {path}: {e}")
        # Refreshed either way: a discard can fail half-way through.
        self._on_files_changed()

    def _ignore_file(self, path: str) -> None:
        if not self._repo_path:
            return
        try:
            _append_to_gitignore(self._repo_path, path)
        except (OSError, UnicodeError) as e:
            self.commit_failed.emit(f"Add to .gitignore failed: {e}")
            return
        self._on_files_changed()

    def _on_stage_all(self) -> None:
        # Closing the last repo can leave this panel on screen with no buses.
        if self._queries is None:
            return
        try:
            raw_files = self._queries.get_working_tree.execute()
            files, partial = _deduplicate(raw_files)
            paths = list({f.path for f in files if f.status != StagingState.STAGED} | partial)
            if not paths:
                return
            self._commands.stage_files.execute(paths)
        except Exception as e:
            self.commit_failed.emit(f"Stage All failed: {e}")
            return
        self._on_files_changed()

    def _on_unstage_all(self) -> None:
        if self._queries is None:
            return
        try:
            raw_files = self._queries.get_working_tree.execute()
            files, partial = _deduplicate(raw_files)
            paths = list({f.path for f in files if f.status == StagingState.STAGED} | partial)
            if not paths:
                return
            self._commands.unstage_files.execute(paths)
        except Exception as e:
            self.commit_failed.emit(f"Unstage All failed: {e}")
            return
        self._on_files_changed()

    def _on_commit_shortcut(self) -> None:
        # Same guard a click has: a disabled button must not commit by keyboard.
        if self._btn_commit.isEnabled():
            self._on_commit()

    def _on_commit(self) -> None:
        if self._queries is None:
            return
        state = getattr(self, "_current_state", "CLEAN")
        msg = self._msg_edit.toPlainText().strip()
        if state not in _OPERATIONS_IN_PROGRESS and not msg:
            self.commit_failed.emit("Commit message is empty")
            return

        # Every path below creates a commit, so identity is required.
        if not self._ensure_identity():
            return

        if state == "MERGING":
            self.merge_continue_requested.emit(msg)
            return
        if state == "REBASING":
            self.rebase_continue_requested.emit(msg)
            return
        if state == "CHERRY_PICKING":
            self.cherry_pick_continue_requested.emit()
            return
        if state == "REVERTING":
            self.revert_continue_requested.emit()
            return

        amending = self._chk_amend.isChecked()
        if amending and not self._confirm_amend_published():
            return

        try:
            if amending:
                self._commands.amend_commit.execute(msg)
            else:
                self._commands.create_commit.execute(msg)
        except Exception as e:
            verb = "Amend" if amending else "Commit"
            self.commit_failed.emit(f"{verb} failed: {e}")
            return

        first_line = msg.split("\n")[0]
        self._draft_msg = ""
        self._msg_edit.clear()
        self._untick_amend()
        self.commit_completed.emit(first_line)
        self.reload_requested.emit()
        self.reload()

    def _on_amend_toggled(self, checked: bool) -> None:
        """Swap the message editor between the user's draft and HEAD's message."""
        if not checked:
            self._msg_edit.setPlainText(self._draft_msg)
            self._btn_commit.setText("Commit")
            return

        self._draft_msg = self._msg_edit.toPlainText()
        try:
            head_message = self._head_commit_message()
        except Exception as e:
            self._refuse_amend(f"Could not read the last commit: {e}")
            return
        if head_message is None:
            self._refuse_amend("Nothing to amend — this branch has no commits yet.")
            return
        self._msg_edit.setPlainText(head_message)
        self._btn_commit.setText("Amend Commit")

    def _refuse_amend(self, reason: str) -> None:
        """Untick without running the handler: the editor still holds the draft."""
        self._chk_amend.blockSignals(True)
        self._chk_amend.setChecked(False)
        self._chk_amend.blockSignals(False)
        self.commit_failed.emit(reason)

    def _head_commit_message(self) -> str | None:
        """Message of the commit HEAD points at, or None on an unborn branch."""
        if self._queries is None:
            return None
        head_oid = self._queries.get_head_oid.execute()
        if not head_oid:
            return None
        return self._queries.get_commit_detail.execute(head_oid).message

    def _confirm_amend_published(self) -> bool:
        """Warn before amending a commit a remote branch still points at.

        Returns True to go ahead. A remote ref on HEAD means the commit has been
        pushed, so amending it rewrites published history.
        """
        try:
            head_oid = self._queries.get_head_oid.execute()
            branches = self._queries.get_branches.execute()
        except Exception as e:
            # Can't tell, so don't block the user; but leave a trace of why.
            logger.warning("Could not check whether HEAD has been pushed: %s", e)
            return True
        published = [b.name for b in branches if b.is_remote and b.target_oid == head_oid]
        if not published:
            return True
        answer = QMessageBox.warning(
            self,
            "Amend a pushed commit?",
            f"{', '.join(published)} still points at this commit.\n\n"
            "Amending rewrites it, so the branch will need a force push and "
            "anyone who already pulled will have to reconcile.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return answer == QMessageBox.Yes

    def _ensure_identity(self) -> bool:
        """Prompt for git identity if missing.

        Returns True when identity is already configured or the user
        successfully sets it via the prompt; False if the user cancels
        or saving fails (in which case commit_failed has been emitted).
        """
        name, email = self._queries.get_identity.execute()
        if name and email:
            return True
        from PySide6.QtWidgets import QDialog

        from git_gui.presentation.dialogs.identity_dialog import IdentityDialog

        dlg = IdentityDialog(name, email, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return False
        new_name, new_email, global_ = dlg.values()
        try:
            self._commands.set_identity.execute(new_name, new_email, global_)
        except Exception as e:
            self.commit_failed.emit(f"Failed to save identity: {e}")
            return False
        return True

    def _on_files_changed(self) -> None:
        self.reload()

    def update_conflict_banner(self, state_name: str, merge_msg: str | None = None) -> None:
        self._current_state = state_name
        # An in-progress merge/rebase/cherry-pick/revert has its own commit path.
        # Untick before labelling: unticking resets the label to "Commit".
        amend_allowed = state_name not in _OPERATIONS_IN_PROGRESS
        if not amend_allowed:
            self._untick_amend()
        self._chk_amend.setEnabled(amend_allowed)
        if state_name == "MERGING":
            self._banner_label.setText("\u26a0 Merge in progress")
            self._conflict_banner.setVisible(True)
            self._btn_commit.setText("Finish Merge")
            if merge_msg and not self._msg_edit.toPlainText().strip():
                self._msg_edit.setPlainText(merge_msg.strip())
        elif state_name == "REBASING":
            self._banner_label.setText("\u26a0 Rebase in progress")
            self._conflict_banner.setVisible(True)
            self._btn_commit.setText("Continue Rebase")
        elif state_name == "CHERRY_PICKING":
            self._banner_label.setText("\u26a0 Cherry-pick in progress")
            self._conflict_banner.setVisible(True)
            self._btn_commit.setText("Continue Cherry-pick")
        elif state_name == "REVERTING":
            self._banner_label.setText("\u26a0 Revert in progress")
            self._conflict_banner.setVisible(True)
            self._btn_commit.setText("Continue Revert")
        else:
            self._conflict_banner.setVisible(False)
            self._btn_commit.setText("Amend Commit" if self._chk_amend.isChecked() else "Commit")

    def _untick_amend(self) -> None:
        """Untick Amend through its handler, so the editor gets the draft back
        instead of keeping HEAD's message."""
        self._chk_amend.setChecked(False)

    def _on_abort_clicked(self) -> None:
        state = getattr(self, "_current_state", "CLEAN")
        if state == "MERGING":
            self.merge_abort_requested.emit()
        elif state == "REBASING":
            self.rebase_abort_requested.emit()
        elif state == "CHERRY_PICKING":
            self.cherry_pick_abort_requested.emit()
        elif state == "REVERTING":
            self.revert_abort_requested.emit()


def _append_to_gitignore(repo_path: str, path: str) -> None:
    """Add *path* to the repo's top-level .gitignore unless it is already listed."""
    gitignore_path = os.path.join(repo_path, ".gitignore")
    pattern = _ignore_pattern(path)
    entry = pattern + "\n"
    if os.path.exists(gitignore_path):
        with open(gitignore_path, encoding="utf-8") as f:
            existing = f.read()
        if pattern in existing.splitlines():
            return
        if not existing.endswith("\n") and existing:
            entry = "\n" + entry
    with open(gitignore_path, "a", encoding="utf-8") as f:
        f.write(entry)


def _ignore_pattern(path: str) -> str:
    """The .gitignore line that matches the repo-relative *path* and nothing else.

    Written raw, a path is a pattern: a leading '#' or '!' makes a comment or
    a negation, '[', '*' and '?' are globs, trailing spaces are dropped, and a
    name with no slash matches at every depth. The leading slash anchors the
    line to the repo root, which also keeps '#' and '!' off its first column.
    """
    escaped = _GITIGNORE_SPECIALS.sub(r"\\\g<0>", path)
    body = escaped.rstrip(" ")
    return "/" + body + "\\ " * (len(escaped) - len(body))


def _conflicts_first(files: list[FileStatus]) -> list[FileStatus]:
    """List order: conflicted files on top, then by path.

    Every refill must use it. A list that reorders after a checkbox click
    moves the row under the pointer, and the next click stages whatever slid
    there, which for a conflicted file marks it resolved.
    """
    return sorted(files, key=lambda f: (f.status != StagingState.CONFLICTED, f.path))


def _deduplicate(files: list[FileStatus]) -> tuple[list[FileStatus], set[str]]:
    """Deduplicate files and detect partial staging.

    Returns (deduped_files, partial_paths). For partial staged files,
    keeps the staged entry so the checkbox starts as checked / "-".
    """
    partial: set[str] = set()
    seen: set[str] = set()
    for f in files:
        if f.path in seen:
            partial.add(f.path)
        seen.add(f.path)

    deduped: list[FileStatus] = []
    added: set[str] = set()
    # First pass: add staged entries (preferred for partial files)
    for f in files:
        if f.path in partial:
            if f.status == StagingState.STAGED and f.path not in added:
                deduped.append(f)
                added.add(f.path)
        elif f.path not in added:
            deduped.append(f)
            added.add(f.path)
    return deduped, partial
