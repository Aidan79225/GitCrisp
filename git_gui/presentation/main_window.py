# git_gui/presentation/main_window.py
from __future__ import annotations
import threading
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QInputDialog, QMainWindow, QMessageBox, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget,
)
from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.domain.ports import IRepoStore
from git_gui.infrastructure.pygit2_repo import Pygit2Repository
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.widgets.diff import DiffWidget
from git_gui.presentation.widgets.graph import GraphWidget
from git_gui.presentation.widgets.log_panel import LogPanel
from git_gui.presentation.dialogs.merge_dialog import MergeDialog
from git_gui.presentation.widgets.clone_dialog import CloneDialog
from git_gui.presentation.widgets.create_tag_dialog import CreateTagDialog
from git_gui.presentation.widgets.repo_list import RepoListWidget
from git_gui.presentation.widgets.sidebar import SidebarWidget
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget
from git_gui.presentation.widgets.insight_dialog import InsightDialog
from git_gui.presentation.menus.appearance import install_appearance_menu
from git_gui.presentation.menus.git_menu import install_git_menu
from git_gui.presentation.dialogs.interactive_rebase_dialog import InteractiveRebaseDialog


class _RemoteSignals(QObject):
    """Signal bridge — lives on main thread, emitted from background thread."""
    finished = Signal(str)
    failed = Signal(str, str)


class _RepoReadySignals(QObject):
    ready = Signal(str, object, object)   # path, QueryBus, CommandBus
    failed = Signal(str, str)             # path, error


class MainWindow(QMainWindow):
    def __init__(self, queries: QueryBus | None, commands: CommandBus | None,
                 repo_store: IRepoStore, remote_tag_cache=None, repo_path: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"GitCrisp — {repo_path}" if repo_path else "GitCrisp")
        self.resize(1400, 800)
        self.menuBar().setStyleSheet(
            "QMenu { padding: 6px; }"
            "QMenu::item { padding: 6px 24px 6px 20px; }"
        )
        install_appearance_menu(self)

        self._queries = queries
        self._commands = commands
        self._repo_store = repo_store
        self._remote_tag_cache = remote_tag_cache
        self._repo_path = repo_path
        self._sidebar = SidebarWidget(queries, commands, remote_tag_cache, repo_path)
        self._graph = GraphWidget(queries, commands)
        self._diff = DiffWidget(queries, commands)
        self._working_tree = WorkingTreeWidget(queries, commands, repo_path=repo_path)
        self._repo_list = RepoListWidget(repo_store)
        self._log_panel = LogPanel()
        self._remote_running = False
        self._selected_oid: str | None = None

        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(self._diff)           # index 0: commit mode
        self._right_stack.addWidget(self._working_tree)    # index 1: working tree

        # Vertical splitter for sidebar: branches on top, repos on bottom
        sidebar_splitter = QSplitter(Qt.Vertical)
        sidebar_splitter.addWidget(self._sidebar)
        sidebar_splitter.addWidget(self._repo_list)
        sidebar_splitter.setSizes([400, 400])

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(sidebar_splitter)
        splitter.addWidget(self._graph)
        splitter.addWidget(self._right_stack)
        splitter.setSizes([220, 230, 950])
        # Lock the handle between graph and right_stack so it can't be dragged
        # Handle index 2 is between widget 1 (graph) and widget 2 (right_stack)
        handle = splitter.handle(2)
        if handle:
            handle.setEnabled(False)
            handle.setCursor(Qt.ArrowCursor)

        # Main layout: splitter on top, log panel at bottom
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(splitter, 1)
        central_layout.addWidget(self._log_panel, 0)

        # F5 reload shortcut (global)
        self._reload_shortcut = QShortcut(QKeySequence(Qt.Key_F5), self)
        self._reload_shortcut.activated.connect(self._reload)

        # Ctrl+F — search commits
        self._search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._search_shortcut.activated.connect(self._graph.open_search)

        # Ctrl+W — close current repo (switch to previous open repo)
        self._close_repo_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        self._close_repo_shortcut.activated.connect(self._close_current_repo)

        # Ctrl+1..9 — switch to Nth open repo
        self._repo_shortcuts: list[QShortcut] = []
        for i in range(1, 10):
            sc = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            sc.activated.connect(lambda idx=i: self._switch_to_repo_index(idx))
            self._repo_shortcuts.append(sc)

        self.setCentralWidget(central)

        # Wire cross-widget signals
        self._graph.commit_selected.connect(self._on_commit_selected)
        self._working_tree.reload_requested.connect(self._reload)
        self._working_tree.merge_abort_requested.connect(self._on_merge_abort)
        self._working_tree.rebase_abort_requested.connect(self._on_rebase_abort)
        self._working_tree.merge_continue_requested.connect(self._on_merge_continue)
        self._working_tree.rebase_continue_requested.connect(self._on_rebase_continue)
        self._working_tree.commit_completed.connect(
            lambda msg: self._log_panel.log(f'Commit: "{msg}"')
        )
        self._working_tree.commit_failed.connect(
            lambda reason: (self._log_panel.expand(), self._log_panel.log_error(reason))
        )
        self._working_tree.working_tree_empty.connect(self._on_working_tree_empty)
        self._working_tree.submodule_open_requested.connect(self._on_submodule_path_clicked)
        self._diff.submodule_open_requested.connect(self._on_submodule_path_clicked)
        self._diff.merge_abort_requested.connect(self._on_merge_abort)
        self._diff.rebase_abort_requested.connect(self._on_rebase_abort)
        self._diff.rebase_continue_requested.connect(
            lambda: self._on_rebase_continue("")
        )
        self._sidebar.branch_checkout_requested.connect(self._on_branch_changed)
        self._sidebar.branch_clicked.connect(self._graph.reload_with_extra_tip)
        self._sidebar.branch_merge_requested.connect(self._on_merge)
        self._sidebar.branch_rebase_requested.connect(self._on_rebase)
        self._sidebar.branch_delete_requested.connect(self._on_delete_branch)
        self._sidebar.fetch_requested.connect(self._on_fetch_single)
        self._sidebar.branch_push_requested.connect(
            lambda b: self._run_remote_op(f"Push origin/{b}", lambda: self._commands.push.execute("origin", b)))
        self._sidebar.stash_pop_requested.connect(self._on_stash_pop)
        self._sidebar.stash_apply_requested.connect(self._on_stash_apply)
        self._sidebar.stash_drop_requested.connect(self._on_stash_drop)
        self._sidebar.stash_clicked.connect(self._on_stash_clicked)

        # Graph context menu signals
        self._graph.create_branch_requested.connect(self._on_create_branch)
        self._graph.checkout_commit_requested.connect(self._on_checkout_commit)
        self._graph.checkout_branch_requested.connect(self._on_checkout_branch)
        self._graph.delete_branch_requested.connect(self._on_delete_branch)
        self._graph.reload_requested.connect(self._reload)
        self._graph.push_requested.connect(self._on_push)
        self._graph.pull_requested.connect(self._on_pull)
        self._graph.fetch_all_requested.connect(self._on_fetch_all_prune)
        self._graph.stash_requested.connect(self._on_stash_requested)
        self._graph.create_tag_requested.connect(self._on_create_tag)
        self._graph.insight_requested.connect(self._on_insight_requested)
        self._graph.merge_branch_requested.connect(self._on_merge)
        self._graph.merge_commit_requested.connect(self._on_merge_commit)
        self._graph.rebase_onto_branch_requested.connect(self._on_rebase)
        self._graph.rebase_onto_commit_requested.connect(self._on_rebase_onto_commit)
        self._graph.interactive_rebase_branch_requested.connect(self._on_interactive_rebase_branch)
        self._graph.interactive_rebase_commit_requested.connect(self._on_interactive_rebase_commit)

        # Sidebar tag signals
        self._sidebar.tag_clicked.connect(self._graph.reload_with_extra_tip)
        self._sidebar.tag_delete_requested.connect(self._on_delete_tag)
        self._sidebar.tag_push_requested.connect(self._on_push_tag)

        # Repo list signals
        self._repo_list.repo_switch_requested.connect(self._switch_repo)
        self._repo_list.repo_open_requested.connect(self._on_repo_open)
        self._repo_list.repo_close_requested.connect(self._on_repo_close)
        self._repo_list.repo_remove_recent_requested.connect(self._on_repo_remove_recent)
        self._repo_list.clone_requested.connect(self._on_clone_requested)

        if self._queries is not None:
            self._reload()
        self._repo_list.reload()
        install_git_menu(
            self,
            queries=self._queries,
            commands=self._commands,
            repo_workdir=self._repo_path,
            on_open_submodule=self._on_submodule_open_requested,
        )

    def _on_working_tree_empty(self) -> None:
        """Working tree has no changes — switch back to commit info and refresh graph."""
        self._graph.reload()
        oid = self._selected_oid
        if not oid or oid == WORKING_TREE_OID:
            if self._queries:
                oid = self._queries.get_head_oid.execute()
        if oid and oid != WORKING_TREE_OID:
            self._right_stack.setCurrentIndex(0)
            self._diff.load_commit(oid)

    def _on_stash_clicked(self, oid: str) -> None:
        self._graph.clear_selection()
        self._right_stack.setCurrentIndex(0)
        self._diff.load_commit(oid)

    def _on_commit_selected(self, oid: str) -> None:
        self._sidebar.clear_stash_selection()
        self._selected_oid = oid
        if oid == WORKING_TREE_OID:
            self._right_stack.setCurrentIndex(1)
            self._working_tree.reload()
        else:
            self._right_stack.setCurrentIndex(0)
            self._diff.load_commit(oid)

    def _reload(self) -> None:
        if self._queries is None:
            return
        self._sidebar.reload()
        self._graph.reload()
        if self._right_stack.currentIndex() == 1:
            self._working_tree.reload()
        if self._queries is not None:
            try:
                state_info = self._queries.get_repo_state.execute()
                state_name = state_info.state.name
                merge_msg = self._queries.get_merge_msg.execute() if state_name == "MERGING" else None
                self._working_tree.update_conflict_banner(state_name, merge_msg)
                self._diff.update_state_banner(state_name)
            except Exception:
                self._working_tree.update_conflict_banner("CLEAN")
                self._diff.update_state_banner("CLEAN")

    def _on_branch_changed(self, branch: str) -> None:
        if self._queries is None:
            return
        self._sidebar.reload()
        head_oid = self._queries.get_head_oid.execute()
        if head_oid:
            self._graph.reload_and_scroll_to(head_oid)
        else:
            self._graph.reload()

    def _on_merge(self, branch: str) -> None:
        try:
            all_branches = self._queries.get_branches.execute()
            target = None
            for b in all_branches:
                if b.name == branch:
                    target = b
                    break
            if not target:
                self._log_panel.log_error(f"Branch not found: {branch}")
                return
            analysis = self._queries.get_merge_analysis.execute(target.target_oid)
            head_branch = self._queries.get_repo_state.execute().head_branch or "HEAD"
            default_msg = f"Merge branch '{branch}'"

            if analysis.is_up_to_date:
                self._log_panel.log(f"Merge {branch}: already up to date")
                return

            dlg = MergeDialog(branch, head_branch, analysis.can_ff, default_msg, parent=self)
            if dlg.exec() != MergeDialog.Accepted:
                return
            req = dlg.result_value()
            self._commands.merge.execute(branch, strategy=req.strategy, message=req.message)
            self._log_panel.log(f"Merge: {branch} into {head_branch}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Merge {branch} — ERROR: {e}")
        self._reload()

    def _on_rebase(self, branch: str) -> None:
        try:
            self._commands.rebase.execute(branch)
            self._log_panel.log(f"Rebase onto {branch}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Rebase onto {branch} — ERROR: {e}")
        self._reload()

    def _on_merge_commit(self, oid: str) -> None:
        try:
            analysis = self._queries.get_merge_analysis.execute(oid)
            head_branch = self._queries.get_repo_state.execute().head_branch or "HEAD"
            short_oid = oid[:7]
            default_msg = f"Merge commit {short_oid}"

            if analysis.is_up_to_date:
                self._log_panel.log(f"Merge commit {short_oid}: already up to date")
                return

            dlg = MergeDialog(f"commit {short_oid}", head_branch, analysis.can_ff, default_msg, parent=self)
            if dlg.exec() != MergeDialog.Accepted:
                return
            req = dlg.result_value()
            self._commands.merge_commit.execute(oid, strategy=req.strategy, message=req.message)
            self._log_panel.log(f"Merge: commit {short_oid} into {head_branch}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Merge commit {short_oid} — ERROR: {e}")
        self._reload()

    def _on_rebase_onto_commit(self, oid: str) -> None:
        try:
            self._commands.rebase_onto_commit.execute(oid)
            self._log_panel.log(f"Rebase onto commit {oid[:7]}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Rebase onto commit {oid[:7]} — ERROR: {e}")
        self._reload()

    def _on_interactive_rebase_branch(self, branch: str) -> None:
        try:
            all_branches = self._queries.get_branches.execute()
            target = None
            for b in all_branches:
                if b.name == branch:
                    target = b
                    break
            if not target:
                self._log_panel.log_error(f"Branch not found: {branch}")
                return
            self._open_interactive_rebase(target.target_oid, branch)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Interactive rebase — ERROR: {e}")

    def _on_interactive_rebase_commit(self, oid: str) -> None:
        self._open_interactive_rebase(oid, f"commit {oid[:7]}")

    def _open_interactive_rebase(self, target_oid: str, target_label: str) -> None:
        try:
            head_oid = self._queries.get_head_oid.execute()
            if not head_oid:
                self._log_panel.log_error("No HEAD — cannot rebase")
                return
            commits = self._queries.get_commit_range.execute(head_oid, target_oid)
            if not commits:
                self._log_panel.log("No commits to rebase")
                return
            dlg = InteractiveRebaseDialog(commits, target_label, parent=self)
            if dlg.exec() != InteractiveRebaseDialog.Accepted:
                return
            entries = dlg.result_entries()
            self._run_remote_op(
                f"Interactive rebase onto {target_label}",
                lambda: self._commands.interactive_rebase.execute(target_oid, entries),
            )
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Interactive rebase — ERROR: {e}")

    def _on_merge_abort(self) -> None:
        try:
            self._commands.merge_abort.execute()
            self._log_panel.log("Merge aborted")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Merge abort — ERROR: {e}")
        self._reload()

    def _on_rebase_abort(self) -> None:
        try:
            self._commands.rebase_abort.execute()
            self._log_panel.log("Rebase aborted")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Rebase abort — ERROR: {e}")
        self._reload()

    def _on_merge_continue(self, msg: str) -> None:
        try:
            if self._queries.has_unresolved_conflicts.execute():
                self._log_panel.expand()
                self._log_panel.log_error("Resolve all conflicts and stage files first")
                return
            commit_msg = msg or self._queries.get_merge_msg.execute() or "Merge commit"
            self._commands.create_commit.execute(commit_msg)
            self._log_panel.log("Merge completed")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Merge continue — ERROR: {e}")
        self._reload()

    def _on_rebase_continue(self, msg: str) -> None:
        try:
            if self._queries.has_unresolved_conflicts.execute():
                self._log_panel.expand()
                self._log_panel.log_error("Resolve all conflicts and stage files first")
                return
            self._commands.rebase_continue.execute(msg)
            self._log_panel.log("Rebase continued")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Rebase continue — ERROR: {e}")
        self._reload()

    def _on_delete_branch(self, branch: str) -> None:
        try:
            self._commands.delete_branch.execute(branch)
            self._log_panel.log(f"Deleted branch: {branch}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Delete branch {branch} — ERROR: {e}")
        self._reload()

    def _on_stash_pop(self, index: int) -> None:
        try:
            self._commands.pop_stash.execute(index)
            self._log_panel.log(f"Stash pop: @{{{index}}}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Stash pop @{{{index}}} — ERROR: {e}")
        self._reload()

    def _on_stash_apply(self, index: int) -> None:
        try:
            self._commands.apply_stash.execute(index)
            self._log_panel.log(f"Stash apply: @{{{index}}}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Stash apply @{{{index}}} — ERROR: {e}")
        self._reload()

    def _on_stash_drop(self, index: int) -> None:
        try:
            self._commands.drop_stash.execute(index)
            self._log_panel.log(f"Stash drop: @{{{index}}}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Stash drop @{{{index}}} — ERROR: {e}")
        self._reload()

    def _on_stash_requested(self) -> None:
        result = QMessageBox.question(
            self,
            "Stash Changes",
            "Would you like to stash all uncommitted changes?\n\n"
            "This will save your modifications and revert the working directory to a clean state.",
        )
        if result != QMessageBox.Yes:
            return
        branch = self._get_current_branch() or "unknown"
        try:
            self._commands.stash.execute(f"WIP on {branch}")
            self._log_panel.log(f"Stash: WIP on {branch}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Stash — ERROR: {e}")
        self._reload()

    def _on_create_branch(self, oid: str) -> None:
        name, ok = QInputDialog.getText(self, "Create Branch", "Branch name:")
        if not ok or not name.strip():
            return
        branch_name = name.strip()
        try:
            self._commands.create_branch.execute(branch_name, oid)
            self._commands.checkout.execute(branch_name)
            self._log_panel.log(f"Created and checked out branch: {branch_name}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Create branch — ERROR: {e}")
        self._reload()

    def _on_insight_requested(self) -> None:
        if self._queries is None:
            return
        dialog = InsightDialog(self._queries, self)
        dialog.exec()

    def _on_create_tag(self, oid: str) -> None:
        dialog = CreateTagDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        name = dialog.tag_name()
        message = dialog.tag_message()
        try:
            self._commands.create_tag.execute(name, oid, message)
            kind = "annotated" if message else "lightweight"
            self._log_panel.log(f"Created {kind} tag: {name}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Create tag — ERROR: {e}")
        self._reload()

    def _on_delete_tag(self, name: str) -> None:
        # Look up which remotes have this tag (cache only — fast, no network).
        remotes_with_tag: list[str] = []
        if self._remote_tag_cache and self._repo_path:
            try:
                cache_data = self._remote_tag_cache.load(self._repo_path)
                for remote, names in cache_data.items():
                    if name in names:
                        remotes_with_tag.append(remote)
            except Exception:
                pass

        if remotes_with_tag:
            remote_list = ", ".join(remotes_with_tag)
            box = QMessageBox(self)
            box.setWindowTitle("Delete Tag")
            box.setText(
                f"Tag '{name}' exists on {remote_list}.\n\n"
                f"Delete locally and from {remote_list}?"
            )
            both_btn = box.addButton("Local + remote", QMessageBox.AcceptRole)
            local_btn = box.addButton("Local only", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            # The global QSS sets `QDialog QPushButton { min-width: 72px; }`
            # which clips longer labels. Override at the dialog level with the
            # same selector specificity.
            box.setStyleSheet(
                "QDialog QPushButton { min-width: 160px; padding: 6px 20px; }"
            )
            box.exec()
            clicked = box.clickedButton()
            if clicked is both_btn:
                self._delete_tag_local_and_remote(name, remotes_with_tag)
            elif clicked is local_btn:
                self._delete_tag_local_only(name)
            return

        # No remote has it — original simple flow.
        if QMessageBox.question(self, "Delete Tag", f"Delete tag '{name}'?") != QMessageBox.Yes:
            return
        self._delete_tag_local_only(name)

    def _delete_tag_local_only(self, name: str) -> None:
        try:
            self._commands.delete_tag.execute(name)
            self._log_panel.log(f"Deleted tag: {name}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Delete tag {name} — ERROR: {e}")
        self._reload()

    def _delete_tag_local_and_remote(self, name: str, remotes: list[str]) -> None:
        # Local delete first (synchronous), then each remote in background.
        try:
            self._commands.delete_tag.execute(name)
            self._log_panel.log(f"Deleted tag: {name}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Delete tag {name} — ERROR: {e}")
            self._reload()
            return

        for remote in remotes:
            def _fn(r=remote):
                self._commands.delete_remote_tag.execute(r, name)
                # Update cache: remove the tag from this remote's list.
                if self._remote_tag_cache and self._repo_path:
                    try:
                        data = self._remote_tag_cache.load(self._repo_path)
                        if r in data and name in data[r]:
                            data[r] = [t for t in data[r] if t != name]
                            self._remote_tag_cache.save(self._repo_path, data)
                    except Exception:
                        pass
            self._run_remote_op(f"Delete tag {name} from {remote}", _fn)
        self._reload()

    def _on_checkout_commit(self, oid: str) -> None:
        try:
            self._commands.checkout_commit.execute(oid)
            self._log_panel.log(f"Checkout (detached HEAD): {oid[:8]}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Checkout {oid[:8]} — ERROR: {e}")
        self._reload()

    def _on_checkout_branch(self, name: str) -> None:
        try:
            if "/" in name:
                local_name = name.split("/", 1)[1]
                existing = {
                    b.name for b in self._queries.get_branches.execute()
                    if not b.is_remote
                }
                if local_name in existing:
                    reply = QMessageBox.question(
                        self,
                        "Local branch exists",
                        f"Local branch '{local_name}' already exists.\n\n"
                        f"Reset it to '{name}' (HEAD)? This discards any local "
                        f"commits and uncommitted changes on '{local_name}'.",
                        QMessageBox.Yes | QMessageBox.Cancel,
                        QMessageBox.Cancel,
                    )
                    if reply != QMessageBox.Yes:
                        return
                    self._commands.checkout.execute(local_name)
                    self._commands.reset_branch_to_ref.execute(local_name, name)
                    self._log_panel.log(f"Reset {local_name} to {name}")
                else:
                    self._commands.checkout_remote_branch.execute(name)
                    self._log_panel.log(f"Checkout remote: {name} → local {local_name}")
            else:
                self._commands.checkout.execute(name)
                self._log_panel.log(f"Checkout branch: {name}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Checkout {name} — ERROR: {e}")
        self._reload()

    def _switch_repo(self, path: str) -> None:
        signals = _RepoReadySignals()
        signals.ready.connect(self._on_repo_ready)
        signals.failed.connect(self._on_repo_failed)
        self._repo_ready_signals = signals  # prevent GC

        def _worker():
            try:
                repo = Pygit2Repository(path)
                queries = QueryBus.from_reader(repo)
                commands = CommandBus.from_writer(repo)
                signals.ready.emit(path, queries, commands)
            except Exception as e:
                signals.failed.emit(path, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_repo_ready(self, path: str, queries: QueryBus, commands: CommandBus) -> None:
        self._queries = queries
        self._commands = commands
        self._repo_path = path
        # set_repo_path BEFORE set_buses — set_buses immediately triggers
        # sidebar.reload() which captures _repo_path in a worker thread for the
        # remote-tag cache lookup. If we set it after, the worker reads the
        # previous repo's cache and the tag synced markers disappear.
        self._sidebar.set_repo_path(path)
        self._sidebar.set_buses(self._queries, self._commands)
        self._graph.set_buses(self._queries, self._commands)
        self._diff.set_buses(self._queries, self._commands)
        self._working_tree.set_buses(self._queries, self._commands)
        self._repo_store.set_active(path)
        self._repo_store.save()
        self._repo_list.reload()
        self.setWindowTitle(f"GitCrisp — {path}")
        # Re-install the Git menu so its actions bind to the new repo.
        bar = self.menuBar()
        for action in list(bar.actions()):
            if action.text() == "&Git":
                bar.removeAction(action)
        install_git_menu(
            self,
            queries=self._queries,
            commands=self._commands,
            repo_workdir=self._repo_path,
            on_open_submodule=self._on_submodule_open_requested,
        )
        self._right_stack.setCurrentIndex(0)

    def _on_repo_failed(self, path: str, error: str) -> None:
        self._log_panel.expand()
        self._log_panel.log_error(f"Cannot open {path}: {error}")

    def _enter_empty_state(self) -> None:
        self._queries = None
        self._commands = None
        self._sidebar.set_buses(None, None)
        self._graph.set_buses(None, None)
        self._diff.set_buses(None, None)
        self._working_tree.set_buses(None, None)
        self._repo_list.reload()
        self.setWindowTitle("GitCrisp")
        bar = self.menuBar()
        for action in list(bar.actions()):
            if action.text() == "&Git":
                bar.removeAction(action)
        install_git_menu(
            self,
            queries=None,
            commands=None,
            repo_workdir=None,
            on_open_submodule=self._on_submodule_open_requested,
        )

    def _on_repo_open(self, path: str) -> None:
        self._repo_store.add_open(path)
        self._repo_store.save()
        self._switch_repo(path)

    def _on_repo_close(self, path: str) -> None:
        self._repo_store.close_repo(path)
        self._repo_store.save()
        open_repos = self._repo_store.get_open_repos()
        if open_repos:
            self._switch_repo(open_repos[0])
        else:
            self._enter_empty_state()

    def _close_current_repo(self) -> None:
        """Ctrl+W: close the active repo and switch to the previous open one."""
        if not self._repo_path:
            return
        self._on_repo_close(self._repo_path)

    def _switch_to_repo_index(self, index: int) -> None:
        """Ctrl+1..9: switch to the Nth open repo (1-based)."""
        open_repos = self._repo_store.get_open_repos()
        i = index - 1  # 0-based
        if i < 0 or i >= len(open_repos):
            return
        path = open_repos[i]
        if path == self._repo_path:
            return  # already active
        self._switch_repo(path)

    def _on_repo_remove_recent(self, path: str) -> None:
        self._repo_store.remove_recent(path)
        self._repo_store.save()
        self._repo_list.reload()

    def _on_clone_requested(self) -> None:
        dialog = CloneDialog(self)
        dialog.clone_completed.connect(self._on_clone_completed)
        dialog.exec()

    def _on_submodule_open_requested(self, abs_path: str) -> None:
        """Open a submodule as a top-level repo (one-way switch).

        Inserts the submodule right after the current (parent) repo in the
        open list, so the sidebar shows submodules grouped under their parent.
        """
        self._repo_store.add_open(abs_path, after=self._repo_path)
        self._repo_store.save()
        self._switch_repo(abs_path)

    def _on_submodule_path_clicked(self, rel_path: str) -> None:
        """Resolve a relative submodule path against the current repo and open it."""
        if not self._repo_path:
            return
        import os
        abs_path = os.path.abspath(os.path.join(self._repo_path, rel_path))
        self._on_submodule_open_requested(abs_path)

    def _on_clone_completed(self, path: str) -> None:
        self._repo_store.add_open(path)
        self._repo_store.save()
        self._switch_repo(path)
        self._log_panel.log(f"Cloned repository: {path}")

    def _get_current_branch(self) -> str | None:
        if self._queries is None:
            return None
        branches = self._queries.get_branches.execute()
        for b in branches:
            if b.is_head and not b.is_remote:
                return b.name
        return None

    def _run_remote_op(self, name: str, fn) -> None:
        if self._remote_running:
            return

        self._log_panel.expand()
        self._log_panel.log(f"{name} — started...")
        self._remote_running = True
        self.statusBar().showMessage(f"\u23f3 {name}...")

        signals = _RemoteSignals()
        signals.finished.connect(self._on_remote_done)
        signals.failed.connect(self._on_remote_error)
        self._remote_signals = signals  # prevent GC

        def _worker():
            try:
                fn()
                signals.finished.emit(name)
            except Exception as e:
                signals.failed.emit(name, str(e))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _on_remote_done(self, name: str) -> None:
        self._log_panel.log(f"{name} — done")
        self._remote_running = False
        self.statusBar().clearMessage()
        self._reload()

    def _on_remote_error(self, name: str, error: str) -> None:
        self._log_panel.log_error(f"{name} — ERROR: {error}")
        self._remote_running = False
        self.statusBar().clearMessage()
        self._reload()

        # Detect push rejection and offer force push
        if name.startswith("Push ") and "non-fast-forward" in error:
            branch = self._get_current_branch()
            if branch:
                reply = QMessageBox.warning(
                    self,
                    "Push Rejected",
                    f"Push was rejected because the remote branch has changes "
                    f"you don't have locally.\n\n"
                    f"Would you like to force push with --force-with-lease?\n"
                    f"This will overwrite the remote branch.",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    self._run_remote_op(
                        f"Force push origin/{branch}",
                        lambda: self._commands.force_push.execute("origin", branch),
                    )

    def _on_push(self) -> None:
        branch = self._get_current_branch()
        if branch:
            self._run_remote_op(
                f"Push origin/{branch}",
                lambda: self._commands.push.execute("origin", branch),
            )

    def _on_pull(self) -> None:
        branch = self._get_current_branch()
        if branch:
            self._run_remote_op(
                f"Pull origin/{branch}",
                lambda: self._commands.pull.execute("origin", branch),
            )

    def _on_fetch_all_prune(self) -> None:
        def _fn():
            self._commands.fetch_all_prune.execute()
            self._update_remote_tag_cache("origin")
        self._run_remote_op("Fetch --all --prune", _fn)

    def _on_fetch_single(self, remote: str) -> None:
        def _fn():
            self._commands.fetch.execute(remote)
            self._update_remote_tag_cache(remote)
        self._run_remote_op(f"Fetch {remote}", _fn)

    def _on_push_tag(self, name: str) -> None:
        def _fn():
            self._commands.push_tag.execute("origin", name)
            self._update_remote_tag_cache("origin")
        self._run_remote_op(f"Push tag {name}", _fn)

    def _update_remote_tag_cache(self, remote: str) -> None:
        if not self._remote_tag_cache or not self._repo_path or not self._queries:
            return
        try:
            remote_tags = self._queries.get_remote_tags.execute(remote)
            data = self._remote_tag_cache.load(self._repo_path)
            data[remote] = remote_tags
            self._remote_tag_cache.save(self._repo_path, data)
        except Exception:
            pass  # cache update failure is non-critical
