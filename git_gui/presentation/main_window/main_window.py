# git_gui/presentation/main_window/main_window.py
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from git_gui.domain.ports import IRepoStore
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.main_window.branch_flows import BranchFlowsMixin
from git_gui.presentation.main_window.cherry_pick_revert_flows import CherryPickRevertFlowsMixin
from git_gui.presentation.main_window.commit_flows import CommitFlowsMixin
from git_gui.presentation.main_window.merge_rebase_flows import MergeRebaseFlowsMixin
from git_gui.presentation.main_window.reload_coordinator import ReloadCoordinatorMixin
from git_gui.presentation.main_window.remote_op_queue import RemoteOpQueueMixin
from git_gui.presentation.main_window.repo_lifecycle import RepoLifecycleMixin, _RepoReadySignals
from git_gui.presentation.main_window.reset_flow import ResetFlowMixin
from git_gui.presentation.main_window.right_panel import RightPanelMixin
from git_gui.presentation.main_window.stash_flows import StashFlowsMixin
from git_gui.presentation.main_window.tag_flows import TagFlowsMixin
from git_gui.presentation.main_window.update_flow import UpdateFlowMixin
from git_gui.presentation.menus.appearance import install_appearance_menu
from git_gui.presentation.menus.git_menu import install_git_menu
from git_gui.presentation.menus.help_menu import install_help_menu
from git_gui.presentation.widgets.diff import DiffWidget
from git_gui.presentation.widgets.graph import GraphWidget
from git_gui.presentation.widgets.log_panel import LogPanel
from git_gui.presentation.widgets.repo_list import RepoListWidget
from git_gui.presentation.widgets.sidebar import SidebarWidget
from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


class MainWindow(
    QMainWindow,
    ReloadCoordinatorMixin,
    RightPanelMixin,
    ResetFlowMixin,
    StashFlowsMixin,
    BranchFlowsMixin,
    CherryPickRevertFlowsMixin,
    TagFlowsMixin,
    MergeRebaseFlowsMixin,
    CommitFlowsMixin,
    RemoteOpQueueMixin,
    RepoLifecycleMixin,
    UpdateFlowMixin,
):
    def __init__(
        self,
        queries: QueryBus | None,
        commands: CommandBus | None,
        repo_store: IRepoStore,
        remote_tag_cache=None,
        repo_path: str | None = None,
        parent=None,
        *,
        session_factory: Callable[[str], tuple[QueryBus, CommandBus]],
    ) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands
        self._repo_store = repo_store
        self._remote_tag_cache = remote_tag_cache
        self._repo_path = repo_path
        self._session_factory = session_factory
        self._worktree_paths_by_branch: dict[str, str] = {}
        self._smart_checkout = None  # SmartCheckout | None — set in _on_repo_ready

        self._build_chrome()
        self._build_widgets()
        self._build_layout()
        self._build_shortcuts()

        self._wire_reload_signals()
        self._wire_right_panel_signals()
        self._wire_reset_flow_signals()
        self._wire_stash_flow_signals()
        self._wire_branch_flow_signals()
        self._wire_cherry_pick_revert_flow_signals()
        self._wire_tag_flow_signals()
        self._wire_merge_rebase_flow_signals()
        self._wire_commit_flow_signals()
        self._wire_remote_op_signals()
        self._wire_repo_lifecycle_signals()

        # Load any persisted graph view mode for the initial repo.
        self._graph.set_repo_path(self._repo_path)

        # Wire cross-widget signals
        self._working_tree.commit_completed.connect(
            lambda msg: self._log_panel.log(f'Commit: "{msg}"')
        )
        self._working_tree.commit_failed.connect(
            lambda reason: (self._log_panel.expand(), self._log_panel.log_error(reason))
        )
        self._sidebar.branch_clicked.connect(self._graph.reload_with_extra_tip)

        # Sidebar tag signals
        self._sidebar.tag_clicked.connect(self._graph.reload_with_extra_tip)

        if self._queries is not None:
            self._reload()
        self._repo_list.reload()
        self._start_update_check()

    def _build_chrome(self) -> None:
        self.setWindowTitle(f"GitCrisp — {self._repo_path}" if self._repo_path else "GitCrisp")
        self.resize(1400, 800)
        self.menuBar().setStyleSheet(
            "QMenu { padding: 6px; }QMenu::item { padding: 6px 24px 6px 20px; }"
        )
        install_appearance_menu(self)

    def _build_widgets(self) -> None:
        self._repo_ready_signals = _RepoReadySignals()
        self._sidebar = SidebarWidget(
            self._queries, self._commands, self._remote_tag_cache, self._repo_path
        )
        self._graph = GraphWidget(self._queries, self._commands, repo_store=self._repo_store)
        self._diff = DiffWidget(self._queries, self._commands)
        self._working_tree = WorkingTreeWidget(
            self._queries, self._commands, repo_path=self._repo_path
        )
        self._repo_list = RepoListWidget(self._repo_store)
        self._log_panel = LogPanel()
        self._remote_running = False
        self._selected_oid: str | None = None
        self._blame_pane = None  # BlamePane | None — occupies _left_stack index 1
        self._change_detector = None  # RepoChangeDetector | None

        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(self._diff)  # index 0: commit mode
        self._right_stack.addWidget(self._working_tree)  # index 1: working tree

    def _build_layout(self) -> None:
        # Vertical splitter for sidebar: branches on top, repos on bottom
        sidebar_splitter = QSplitter(Qt.Vertical)
        sidebar_splitter.addWidget(self._sidebar)
        sidebar_splitter.addWidget(self._repo_list)
        sidebar_splitter.setSizes([400, 400])

        # The commit list shares its column with blame: blame's job is to get
        # you from a line to the change behind it, so it needs to sit beside the
        # diff pane, and the commit list is what can give way for that.
        self._left_stack = QStackedWidget()
        self._left_stack.addWidget(self._graph)  # index 0: commit list

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(sidebar_splitter)
        splitter.addWidget(self._left_stack)
        splitter.addWidget(self._right_stack)
        self._splitter = splitter
        self._graph_sizes = [220, 230, 950]
        # Blame and the diff both need room, and the split trades one against
        # the other. Measured on a 1600px window: this leaves ~70 columns of
        # code (15% of lines needing a horizontal scroll) and ~470px of diff.
        # Giving blame more starves the diff it hands off to; less, and a
        # third of the code is off screen.
        self._blame_sizes = [220, 900, 480]
        splitter.setSizes(self._graph_sizes)

        # Main layout: splitter on top, log panel at bottom
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(splitter, 1)
        central_layout.addWidget(self._log_panel, 0)

        self.setCentralWidget(central)

    def _build_shortcuts(self) -> None:
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

        install_git_menu(
            self,
            queries=self._queries,
            commands=self._commands,
            repo_workdir=self._repo_path,
            on_open_submodule=self._on_submodule_open_requested,
        )
        install_help_menu(self)
