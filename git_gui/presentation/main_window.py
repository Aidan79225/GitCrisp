# git_gui/presentation/main_window.py
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QSplitter, QToolBar
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.widgets.diff import DiffWidget
from git_gui.presentation.widgets.graph import GraphWidget
from git_gui.presentation.widgets.sidebar import SidebarWidget


class MainWindow(QMainWindow):
    def __init__(self, queries: QueryBus, commands: CommandBus, repo_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"git gui — {repo_path}")
        self.resize(1400, 800)

        self._commands = commands
        self._sidebar = SidebarWidget(queries, commands)
        self._graph = GraphWidget(queries, commands)
        self._diff = DiffWidget(queries, commands)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._graph)
        splitter.addWidget(self._diff)
        splitter.setSizes([220, 230, 950])
        self._toolbar = QToolBar("Main")
        self._reload_action = QAction("Reload", self)
        self._reload_action.setShortcut(QKeySequence(Qt.Key_F5))
        self._reload_action.triggered.connect(self._reload)
        self._toolbar.addAction(self._reload_action)
        self.addToolBar(self._toolbar)
        self.setCentralWidget(splitter)

        # Wire cross-widget signals
        self._graph.commit_selected.connect(self._diff.load_commit)
        self._sidebar.branch_checkout_requested.connect(self._on_branch_changed)
        self._sidebar.branch_merge_requested.connect(
            lambda b: (commands.merge.execute(b), self._reload()))
        self._sidebar.branch_rebase_requested.connect(
            lambda b: (commands.rebase.execute(b), self._reload()))
        self._sidebar.branch_delete_requested.connect(
            lambda b: (commands.delete_branch.execute(b), self._reload()))
        self._sidebar.fetch_requested.connect(
            lambda r: (commands.fetch.execute(r), self._reload()))
        self._sidebar.branch_push_requested.connect(
            lambda b: (commands.push.execute("origin", b), self._reload()))

        self._reload()

    def _reload(self) -> None:
        self._sidebar.reload()
        self._graph.reload()

    def _on_branch_changed(self, branch: str) -> None:
        self._reload()
