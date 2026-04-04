# git_gui/presentation/main_window.py
from __future__ import annotations
import threading
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QInputDialog, QMainWindow, QSplitter, QStackedWidget, QToolBar,
    QVBoxLayout, QWidget,
)
from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.domain.ports import IRepoStore
from git_gui.infrastructure.pygit2_repo import Pygit2Repository
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.widgets.diff import DiffWidget
from git_gui.presentation.widgets.graph import GraphWidget
from git_gui.presentation.widgets.log_panel import LogPanel
from git_gui.presentation.widgets.repo_list import RepoListWidget
from git_gui.presentation.widgets.sidebar import SidebarWidget
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


class _RemoteSignals(QObject):
    """Signal bridge — lives on main thread, emitted from background thread."""
    finished = Signal(str)
    failed = Signal(str, str)


class _RepoReadySignals(QObject):
    ready = Signal(str, object, object)   # path, QueryBus, CommandBus
    failed = Signal(str, str)             # path, error


class MainWindow(QMainWindow):
    def __init__(self, queries: QueryBus | None, commands: CommandBus | None,
                 repo_store: IRepoStore, repo_path: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"GitStack — {repo_path}" if repo_path else "GitStack")
        self.resize(1400, 800)

        self._queries = queries
        self._commands = commands
        self._repo_store = repo_store
        self._sidebar = SidebarWidget(queries, commands)
        self._graph = GraphWidget(queries, commands)
        self._diff = DiffWidget(queries, commands)
        self._working_tree = WorkingTreeWidget(queries, commands)
        self._repo_list = RepoListWidget(repo_store)
        self._log_panel = LogPanel()
        self._remote_running = False

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

        # Main layout: splitter on top, log panel at bottom
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(splitter, 1)
        central_layout.addWidget(self._log_panel, 0)

        self._toolbar = QToolBar("Main")
        self._reload_action = QAction("Reload", self)
        self._reload_action.setShortcut(QKeySequence(Qt.Key_F5))
        self._reload_action.triggered.connect(self._reload)
        self._toolbar.addAction(self._reload_action)

        self._push_action = QAction("Push", self)
        self._push_action.triggered.connect(self._on_push)
        self._toolbar.addAction(self._push_action)

        self._pull_action = QAction("Pull", self)
        self._pull_action.triggered.connect(self._on_pull)
        self._toolbar.addAction(self._pull_action)

        self._fetch_all_action = QAction("Fetch All -p", self)
        self._fetch_all_action.triggered.connect(self._on_fetch_all_prune)
        self._toolbar.addAction(self._fetch_all_action)

        self.addToolBar(self._toolbar)
        self.setCentralWidget(central)

        # Wire cross-widget signals
        self._graph.commit_selected.connect(self._on_commit_selected)
        self._working_tree.reload_requested.connect(self._reload)
        self._working_tree.commit_completed.connect(
            lambda msg: self._log_panel.log(f'Commit: "{msg}"')
        )
        self._working_tree.commit_failed.connect(
            lambda reason: (self._log_panel.expand(), self._log_panel.log_error(reason))
        )
        self._sidebar.branch_checkout_requested.connect(self._on_branch_changed)
        self._sidebar.branch_merge_requested.connect(self._on_merge)
        self._sidebar.branch_rebase_requested.connect(self._on_rebase)
        self._sidebar.branch_delete_requested.connect(self._on_delete_branch)
        self._sidebar.fetch_requested.connect(
            lambda r: self._run_remote_op(f"Fetch {r}", lambda: self._commands.fetch.execute(r)))
        self._sidebar.branch_push_requested.connect(
            lambda b: self._run_remote_op(f"Push origin/{b}", lambda: self._commands.push.execute("origin", b)))
        self._sidebar.stash_pop_requested.connect(self._on_stash_pop)
        self._sidebar.stash_apply_requested.connect(self._on_stash_apply)
        self._sidebar.stash_drop_requested.connect(self._on_stash_drop)

        # Graph context menu signals
        self._graph.create_branch_requested.connect(self._on_create_branch)
        self._graph.checkout_commit_requested.connect(self._on_checkout_commit)
        self._graph.checkout_branch_requested.connect(self._on_checkout_branch)

        # Repo list signals
        self._repo_list.repo_switch_requested.connect(self._switch_repo)
        self._repo_list.repo_open_requested.connect(self._on_repo_open)
        self._repo_list.repo_close_requested.connect(self._on_repo_close)
        self._repo_list.repo_remove_recent_requested.connect(self._on_repo_remove_recent)

        if self._queries is not None:
            self._reload()
        self._repo_list.reload()

    def _on_commit_selected(self, oid: str) -> None:
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

    def _on_branch_changed(self, branch: str) -> None:
        self._reload()

    def _on_merge(self, branch: str) -> None:
        try:
            self._commands.merge.execute(branch)
            self._log_panel.log(f"Merge: {branch} into current")
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
                # Remote branch — create local tracking branch
                self._commands.checkout_remote_branch.execute(name)
                local_name = name.split("/", 1)[1]
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
        self._sidebar.set_buses(self._queries, self._commands)
        self._graph.set_buses(self._queries, self._commands)
        self._diff.set_buses(self._queries, self._commands)
        self._working_tree.set_buses(self._queries, self._commands)
        self._repo_store.set_active(path)
        self._repo_store.save()
        self._repo_list.reload()
        self.setWindowTitle(f"GitStack — {path}")
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
        self.setWindowTitle("GitStack")

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

    def _on_repo_remove_recent(self, path: str) -> None:
        self._repo_store.remove_recent(path)
        self._repo_store.save()
        self._repo_list.reload()

    def _get_current_branch(self) -> str | None:
        if self._queries is None:
            return None
        branches = self._queries.get_branches.execute()
        for b in branches:
            if b.is_head and not b.is_remote:
                return b.name
        return None

    def _set_remote_buttons_enabled(self, enabled: bool) -> None:
        self._push_action.setEnabled(enabled)
        self._pull_action.setEnabled(enabled)
        self._fetch_all_action.setEnabled(enabled)

    def _run_remote_op(self, name: str, fn) -> None:
        if self._remote_running:
            return

        self._log_panel.expand()
        self._log_panel.log(f"{name} — started...")
        self._set_remote_buttons_enabled(False)
        self._remote_running = True

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
        self._set_remote_buttons_enabled(True)
        self._reload()

    def _on_remote_error(self, name: str, error: str) -> None:
        self._log_panel.log_error(f"{name} — ERROR: {error}")
        self._remote_running = False
        self._set_remote_buttons_enabled(True)
        self._reload()

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
        self._run_remote_op(
            "Fetch --all --prune",
            lambda: self._commands.fetch_all_prune.execute(),
        )
