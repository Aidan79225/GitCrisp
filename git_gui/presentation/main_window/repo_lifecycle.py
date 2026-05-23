# git_gui/presentation/main_window/repo_lifecycle.py
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.menus.git_menu import install_git_menu
from git_gui.presentation.services.repo_change_detector import RepoChangeDetector


class _RepoReadySignals(QObject):
    ready = Signal(str, object, object)  # path, QueryBus, CommandBus
    failed = Signal(str, str)  # path, error


class RepoLifecycleMixin:
    """Repo lifecycle — switching, opening, closing, empty-state, recents.

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes (self._queries, self._commands, self._repo_path, self._repo_store,
    self._session_factory, widget refs, ...) set up by MainWindow's __init__.
    """

    def _wire_repo_lifecycle_signals(self) -> None:
        self._repo_list.repo_switch_requested.connect(self._switch_repo)
        self._repo_list.repo_open_requested.connect(self._on_repo_open)
        self._repo_list.repo_close_requested.connect(self._on_repo_close)
        self._repo_list.repo_remove_recent_requested.connect(self._on_repo_remove_recent)
        self._repo_ready_signals.ready.connect(self._on_repo_ready)
        self._repo_ready_signals.failed.connect(self._on_repo_failed)

    def _stop_change_detector(self) -> None:
        """Stop and release the current change detector, if any."""
        if self._change_detector is not None:
            self._change_detector.stop()
            self._change_detector.deleteLater()
            self._change_detector = None

    def _switch_repo(self, path: str) -> None:
        signals = self._repo_ready_signals

        def _worker():
            try:
                queries, commands = self._session_factory(path)
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
        self._graph.set_repo_path(path)
        self._graph.set_buses(self._queries, self._commands)
        self._diff.set_buses(self._queries, self._commands)
        self._working_tree.set_repo_path(path)
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
            on_open_worktrees_dialog=getattr(self, "_open_worktrees_dialog", None),
        )
        self._right_stack.setCurrentIndex(0)

        # Replace any previous detector and start watching this repo.
        self._stop_change_detector()
        self._change_detector = RepoChangeDetector(
            repo_path=path,
            on_reload=self._reload,
            parent=self,
        )

    def _on_repo_failed(self, path: str, error: str) -> None:
        self._log_panel.expand()
        self._log_panel.log_error(f"Cannot open {path}: {error}")

    def _enter_empty_state(self) -> None:
        self._stop_change_detector()
        self._queries = None
        self._commands = None
        self._repo_path = None
        self._sidebar.set_repo_path(None)
        self._sidebar.set_buses(None, None)
        self._graph.set_repo_path(None)
        self._graph.set_buses(None, None)
        self._diff.set_buses(None, None)
        self._working_tree.set_repo_path(None)
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
            on_open_worktrees_dialog=None,
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
