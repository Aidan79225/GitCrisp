# git_gui/presentation/widgets/working_tree.py
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QBrush, QPainter
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
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from git_gui.domain.entities import FileStatus
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.theme import connect_widget, get_theme_manager
from git_gui.presentation.widgets.file_list_view import FileListView as _FileListView
from git_gui.presentation.widgets.hunk_diff import HunkDiffWidget
from git_gui.presentation.widgets.working_tree_model import WorkingTreeModel

# (label only — color comes from theme.colors.status_color(kind) at paint time)
_DELTA_LABEL = {
    "modified": "M",
    "added": "A",
    "deleted": "D",
    "renamed": "R",
    "unknown": "?",
    "conflicted": "C",
}
_BADGE_SIZE = 20
_BADGE_GAP = 6


class _FileDelegate(QStyledItemDelegate):
    """Adds a delta badge between the native checkbox and filename."""

    def initStyleOption(self, option: QStyleOptionViewItem, index) -> None:
        super().initStyleOption(option, index)
        # Prefix badge letter to display text so Qt reserves space;
        # we'll paint the badge over this prefix area
        # Add padding spaces to make room for the badge we'll paint
        option.text = "          " + (option.text or "")

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        # Fill selection background explicitly before Qt draws over it
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, get_theme_manager().current.colors.as_qcolor("primary"))

        # Let Qt draw checkbox + text normally
        super().paint(painter, option, index)

        # Now paint the delta badge in the gap we reserved
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        rect = option.rect
        fs = index.data(Qt.UserRole)
        kind = fs.status if fs else "unknown"
        delta = fs.delta if fs else "unknown"
        badge_key = kind if kind == "conflicted" else delta
        label = _DELTA_LABEL.get(badge_key, "?")

        # Position badge after the checkbox area (~30px from left)
        badge_x = rect.left() + 30
        badge_y = rect.top() + (rect.height() - _BADGE_SIZE) // 2
        badge_rect = QRect(badge_x, badge_y, _BADGE_SIZE, _BADGE_SIZE)
        painter.setBrush(QBrush(get_theme_manager().current.colors.status_color(badge_key)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(badge_rect, 3, 3)
        painter.setPen(get_theme_manager().current.colors.as_qcolor("on_badge"))
        painter.drawText(badge_rect, Qt.AlignCenter, label)

        painter.restore()


class _LoadSignals(QObject):
    done = Signal(list, set)  # files, partial


class WorkingTreeWidget(QWidget):
    reload_requested = Signal()
    commit_completed = Signal(str)  # emits first line of commit message
    commit_failed = Signal(str)  # emits error reason
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

        # ── Conflict banner (hidden by default) ─────────────────────────
        self._conflict_banner = QWidget()
        banner_layout = QHBoxLayout(self._conflict_banner)
        banner_layout.setContentsMargins(8, 6, 8, 6)
        self._banner_label = QLabel("")
        self._banner_label.setStyleSheet("font-weight: bold;")
        self._btn_abort = QPushButton("Abort")
        banner_layout.addWidget(self._banner_label, 1)
        banner_layout.addWidget(self._btn_abort)
        self._conflict_banner.setStyleSheet(
            "background-color: #5c2d2d; border: none; padding: 2px;"
        )
        self._conflict_banner.setVisible(False)

        # ── Row 1: commit toolbar ────────────────────────────────────────────
        self._msg_edit = QPlainTextEdit()
        self._msg_edit.setPlaceholderText("Commit message...")
        self._msg_edit.setMaximumHeight(80)

        self._btn_stage_all = QPushButton("Stage All")
        self._btn_unstage_all = QPushButton("Unstage All")
        self._btn_commit = QPushButton("Commit")
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
        self._chk_amend.toggled.connect(self._on_amend_toggled)
        self._file_model.files_changed.connect(self._on_files_changed)
        self._hunk_diff.hunk_toggled.connect(self._on_files_changed)
        self._hunk_diff.discard_hunk_requested.connect(lambda *_: self._on_files_changed())
        self._hunk_diff.submodule_open_requested.connect(self.submodule_open_requested)
        self._btn_abort.clicked.connect(self._on_abort_clicked)

        connect_widget(self)

    def set_buses(self, queries: QueryBus | None, commands: CommandBus | None) -> None:
        self._queries = queries
        self._commands = commands
        # Amend targets the old repo's HEAD; switching repos must not carry it over.
        self._set_amend_checked(False)
        self._draft_msg = ""
        self._file_model.set_commands(commands)
        self._hunk_diff.set_buses(queries, commands)
        if queries is None:
            self._file_model.reload([], set())
            self._hunk_diff.clear()

    def set_repo_path(self, path: str | None) -> None:
        """Update the active repo path used by _ignore_file and any other
        path-sensitive helper. Called on repo switch by the composite."""
        self._repo_path = path

    def reload(self) -> None:
        queries = self._queries

        signals = _LoadSignals()
        signals.done.connect(self._on_reload_done)
        self._load_signals = signals  # prevent GC

        def _worker():
            raw_files = queries.get_working_tree.execute()
            files, partial = _deduplicate(raw_files)
            signals.done.emit(files, partial)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_reload_done(self, files: list[FileStatus], partial: set[str]) -> None:
        if self._queries is None:
            return
        sorted_files = sorted(files, key=lambda f: (0 if f.status == "conflicted" else 1, f.path))
        self._file_model.reload(sorted_files, partial)
        if not files:
            self._hunk_diff.clear()
            self.working_tree_empty.emit()
        else:
            # No selection after reload — show all files' hunks
            self._hunk_diff.load_all_files([f.path for f in files])

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
        self._commands.discard_file.execute(path)
        self._on_files_changed()

    def _ignore_file(self, path: str) -> None:
        import os

        if not self._repo_path:
            return
        gitignore_path = os.path.join(self._repo_path, ".gitignore")
        entry = path + "\n"
        if os.path.exists(gitignore_path):
            with open(gitignore_path, encoding="utf-8") as f:
                existing = f.read()
            if path in existing.splitlines():
                return
            if not existing.endswith("\n") and existing:
                entry = "\n" + entry
        with open(gitignore_path, "a", encoding="utf-8") as f:
            f.write(entry)
        self._on_files_changed()

    def _on_stage_all(self) -> None:
        raw_files = self._queries.get_working_tree.execute()
        files, partial = _deduplicate(raw_files)
        paths = list({f.path for f in files if f.status != "staged"} | partial)
        if paths:
            self._commands.stage_files.execute(paths)
            self._on_files_changed()

    def _on_unstage_all(self) -> None:
        raw_files = self._queries.get_working_tree.execute()
        files, partial = _deduplicate(raw_files)
        paths = list({f.path for f in files if f.status == "staged"} | partial)
        if paths:
            self._commands.unstage_files.execute(paths)
            self._on_files_changed()

    def _on_commit(self) -> None:
        state = getattr(self, "_current_state", "CLEAN")
        msg = self._msg_edit.toPlainText().strip()
        if state == "CLEAN" and not msg:
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
        self._set_amend_checked(False)
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
        head_message = self._head_commit_message()
        if head_message is None:
            # Unborn branch — nothing to amend. Bounce the checkbox back.
            self._chk_amend.blockSignals(True)
            self._chk_amend.setChecked(False)
            self._chk_amend.blockSignals(False)
            self.commit_failed.emit("Nothing to amend — this branch has no commits yet.")
            return
        self._msg_edit.setPlainText(head_message)
        self._btn_commit.setText("Amend Commit")

    def _head_commit_message(self) -> str | None:
        """Message of the commit HEAD points at, or None on an unborn branch."""
        if self._queries is None:
            return None
        try:
            head_oid = self._queries.get_head_oid.execute()
            if not head_oid:
                return None
            return self._queries.get_commit_detail.execute(head_oid).message
        except Exception:
            return None

    def _confirm_amend_published(self) -> bool:
        """Warn before amending a commit a remote branch still points at.

        Returns True to go ahead. A remote ref on HEAD means the commit has been
        pushed, so amending it rewrites published history.
        """
        try:
            head_oid = self._queries.get_head_oid.execute()
            branches = self._queries.get_branches.execute()
        except Exception:
            return True  # can't tell — don't block the user
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
        # Remember selected path before reload clears selection
        selected_path = None
        idx = self._file_view.currentIndex()
        if idx.isValid():
            fs = self._file_model.data(idx, Qt.UserRole)
            if fs:
                selected_path = fs.path

        queries = self._queries

        signals = _LoadSignals()
        signals.done.connect(
            lambda files, partial: self._on_files_changed_done(files, partial, selected_path)
        )
        self._load_signals = signals  # prevent GC

        def _worker():
            raw_files = queries.get_working_tree.execute()
            files, partial = _deduplicate(raw_files)
            signals.done.emit(files, partial)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_files_changed_done(
        self, files: list[FileStatus], partial: set[str], selected_path: str | None
    ) -> None:
        if self._queries is None:
            return
        self._file_model.reload(files, partial)

        if not files:
            self._hunk_diff.clear()
            self.working_tree_empty.emit()
            return

        # Restore selection by path and refresh hunk diff
        if selected_path:
            for row in range(self._file_model.rowCount()):
                fs = self._file_model.data(self._file_model.index(row), Qt.UserRole)
                if fs and fs.path == selected_path:
                    self._file_view.setCurrentIndex(self._file_model.index(row))
                    self._hunk_diff.load_file(selected_path)
                    return

        # No selection (or selected file disappeared) — show all files' hunks
        self._hunk_diff.load_all_files([f.path for f in files])

    def update_conflict_banner(self, state_name: str, merge_msg: str | None = None) -> None:
        """Show or hide the conflict banner based on repo state."""
        self._current_state = state_name
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
        # An in-progress merge/rebase/cherry-pick/revert has its own commit path.
        self._chk_amend.setEnabled(state_name == "CLEAN")
        if state_name != "CLEAN":
            self._set_amend_checked(False)

    def _set_amend_checked(self, checked: bool) -> None:
        """Set the Amend checkbox without running the message-swap handler."""
        if self._chk_amend.isChecked() == checked:
            return
        self._chk_amend.blockSignals(True)
        self._chk_amend.setChecked(checked)
        self._chk_amend.blockSignals(False)
        self._btn_commit.setText("Amend Commit" if checked else "Commit")

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
            if f.status == "staged" and f.path not in added:
                deduped.append(f)
                added.add(f.path)
        elif f.path not in added:
            deduped.append(f)
            added.add(f.path)
    return deduped, partial
