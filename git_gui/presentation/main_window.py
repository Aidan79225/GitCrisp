# git_gui/presentation/main_window.py
from __future__ import annotations
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
)
from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.widgets.diff import DiffWidget
from git_gui.presentation.widgets.graph import GraphWidget
from git_gui.presentation.widgets.log_panel import LogPanel
from git_gui.presentation.widgets.sidebar import SidebarWidget
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


class _RemoteWorker(QObject):
    finished = Signal(str)       # emits operation name on success
    failed = Signal(str, str)    # emits (operation name, error message)

    def __init__(self, name: str, fn) -> None:
        super().__init__()
        self._name = name
        self._fn = fn

    def run(self) -> None:
        try:
            self._fn()
            self.finished.emit(self._name)
        except Exception as e:
            self.failed.emit(self._name, str(e))


class MainWindow(QMainWindow):
    def __init__(self, queries: QueryBus, commands: CommandBus, repo_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"git gui — {repo_path}")
        self.resize(1400, 800)

        self._queries = queries
        self._commands = commands
        self._sidebar = SidebarWidget(queries, commands)
        self._graph = GraphWidget(queries, commands)
        self._diff = DiffWidget(queries, commands)
        self._working_tree = WorkingTreeWidget(queries, commands)
        self._log_panel = LogPanel()
        self._remote_thread: QThread | None = None

        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(self._diff)           # index 0: commit mode
        self._right_stack.addWidget(self._working_tree)    # index 1: working tree

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._sidebar)
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
        self._sidebar.branch_merge_requested.connect(
            lambda b: (commands.merge.execute(b), self._reload()))
        self._sidebar.branch_rebase_requested.connect(
            lambda b: (commands.rebase.execute(b), self._reload()))
        self._sidebar.branch_delete_requested.connect(
            lambda b: (commands.delete_branch.execute(b), self._reload()))
        self._sidebar.fetch_requested.connect(
            lambda r: self._run_remote_op(f"Fetch {r}", lambda: commands.fetch.execute(r)))
        self._sidebar.branch_push_requested.connect(
            lambda b: self._run_remote_op(f"Push origin/{b}", lambda: commands.push.execute("origin", b)))

        self._reload()

    def _on_commit_selected(self, oid: str) -> None:
        if oid == WORKING_TREE_OID:
            self._right_stack.setCurrentIndex(1)
            self._working_tree.reload()
        else:
            self._right_stack.setCurrentIndex(0)
            self._diff.load_commit(oid)

    def _reload(self) -> None:
        self._sidebar.reload()
        self._graph.reload()

    def _on_branch_changed(self, branch: str) -> None:
        self._reload()

    def _get_current_branch(self) -> str | None:
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
        if self._remote_thread is not None:
            return  # already running a remote op

        self._log_panel.expand()
        self._log_panel.log(f"{name} — started...")
        self._set_remote_buttons_enabled(False)

        thread = QThread()
        worker = _RemoteWorker(name, fn)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(lambda n: self._on_remote_done(n))
        worker.failed.connect(lambda n, e: self._on_remote_error(n, e))
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)

        self._remote_thread = thread
        self._remote_worker = worker  # prevent GC
        thread.start()

    def _on_remote_done(self, name: str) -> None:
        self._log_panel.log(f"{name} — done")
        self._set_remote_buttons_enabled(True)
        self._reload()

    def _on_remote_error(self, name: str, error: str) -> None:
        self._log_panel.log_error(f"{name} — ERROR: {error}")
        self._set_remote_buttons_enabled(True)
        self._reload()

    def _on_thread_finished(self) -> None:
        # Clean up after thread has fully stopped
        if self._remote_thread is not None:
            self._remote_thread.deleteLater()
            self._remote_thread = None
        if self._remote_worker is not None:
            self._remote_worker.deleteLater()
            self._remote_worker = None

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
