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


class _WorktreeOpSignals(QObject):
    succeeded = Signal()
    dirty_error = Signal(str)
    locked_error = Signal(str, str)  # path, reason
    failed = Signal(str)
    added = Signal(str, bool)  # new worktree path, switch_after


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
        self._repo_list.worktree_action_requested.connect(self._on_worktree_action)
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
        # Blame windows show a file from the repo being left behind.
        self._close_blame_windows()
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

        # (Re)build SmartCheckout bound to the freshly created buses.
        from git_gui.presentation.services.smart_checkout import SmartCheckout

        if getattr(self, "_smart_checkout", None) is not None:
            self._smart_checkout.deleteLater()
            self._smart_checkout = None
        self._smart_checkout = SmartCheckout(
            checkout=self._commands.checkout,
            finder=self._queries.find_worktree_for_branch,
            parent=self,
        )
        self._smart_checkout.switch_to_worktree_requested.connect(self._switch_repo)
        if hasattr(self._sidebar, "set_smart_checkout"):
            self._sidebar.set_smart_checkout(self._smart_checkout)

        # Bridge branch -> "Checkout in New Worktree…" requests from
        # sidebar / graph context menus to the Add Worktree dialog.
        # Disconnect prior connections (idempotent via try/except).
        for sig_owner_attr in ("_sidebar", "_graph"):
            owner = getattr(self, sig_owner_attr, None)
            if owner is not None and hasattr(owner, "checkout_in_new_worktree_requested"):
                try:
                    owner.checkout_in_new_worktree_requested.disconnect()
                except (RuntimeError, TypeError):
                    pass  # No prior connection
        # Now connect fresh.
        if hasattr(self._sidebar, "checkout_in_new_worktree_requested"):
            self._sidebar.checkout_in_new_worktree_requested.connect(
                lambda branch: self._open_add_worktree_dialog(
                    preselect_branch=branch, default_create=False
                )
            )
        if hasattr(self._graph, "checkout_in_new_worktree_requested"):
            self._graph.checkout_in_new_worktree_requested.connect(
                lambda branch: self._open_add_worktree_dialog(
                    preselect_branch=branch, default_create=False
                )
            )

        # Load worktree list, paint badges/sidebar entries, refresh repo list.
        self._load_worktrees_for_active_repo()

    def _on_repo_failed(self, path: str, error: str) -> None:
        self._log_panel.expand()
        self._log_panel.log_error(f"Cannot open {path}: {error}")

    def _enter_empty_state(self) -> None:
        self._stop_change_detector()
        self._close_blame_windows()
        self._queries = None
        self._commands = None
        self._repo_path = None
        self._smart_checkout = None
        self._worktree_paths_by_branch = {}
        self._sidebar.set_repo_path(None)
        self._sidebar.set_buses(None, None)
        if hasattr(self._sidebar, "set_smart_checkout"):
            self._sidebar.set_smart_checkout(None)
        if hasattr(self._sidebar, "set_worktree_branches"):
            self._sidebar.set_worktree_branches(set())
        self._graph.set_repo_path(None)
        self._graph.set_buses(None, None)
        self._diff.set_buses(None, None)
        self._working_tree.set_repo_path(None)
        self._working_tree.set_buses(None, None)
        self._repo_list.set_active_worktrees([])
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

    # ── Worktree orchestration ────────────────────────────────────────────

    def _load_worktrees_for_active_repo(self) -> None:
        if self._queries is None or self._repo_path is None:
            return
        # When the active path is a linked worktree (not a top-level open repo),
        # its session reports worktree metadata relative to itself — its own
        # directory as the main worktree, with the real main repo absent. Re-
        # listing here would corrupt the group shown in the repo list. Keep the
        # group loaded for the owning main repo and just refresh the active
        # highlight onto the worktree row.
        if self._repo_path not in self._repo_store.get_open_repos():
            self._repo_list.reload()
            return
        try:
            wts = self._queries.list_worktrees.execute()
        except Exception as e:
            self._log_panel.log_error(f"Failed to list worktrees: {e}")
            wts = []
        self._repo_list.set_active_worktrees(wts, owner_path=self._repo_path)
        self._repo_list.reload()
        wt_branches = {wt.branch for wt in wts if wt.branch and not wt.is_main}
        wt_paths = {wt.branch: str(wt.path) for wt in wts if wt.branch and not wt.is_main}
        if hasattr(self._sidebar, "set_worktree_branches"):
            self._sidebar.set_worktree_branches(wt_branches)
        self._worktree_paths_by_branch = wt_paths

    def _on_worktree_action(self, action: str, path: str) -> None:
        if action == "add":
            self._open_add_worktree_dialog(preselect_branch=None, default_create=False)
        elif action == "manage":
            self._open_worktrees_dialog()
        elif action == "open":
            self._switch_repo(path)
        elif action == "lock":
            self._run_lock_worktree(path)
        elif action == "unlock":
            self._run_unlock_worktree(path)
        elif action == "remove":
            self._begin_remove_worktree(path)

    def _open_add_worktree_dialog(
        self,
        *,
        preselect_branch: str | None,
        default_create: bool,
    ) -> None:
        if self._queries is None or self._commands is None or self._repo_path is None:
            return
        from git_gui.presentation.dialogs.add_worktree_dialog import AddWorktreeDialog

        try:
            branches = [b.name for b in self._queries.get_branches.execute() if not b.is_remote]
        except Exception:
            branches = []
        in_use: dict[str, str] = {}
        try:
            for wt in self._queries.list_worktrees.execute():
                if wt.branch and not wt.is_main:
                    in_use[wt.branch] = str(wt.path)
        except Exception:
            pass
        dlg = AddWorktreeDialog(
            repo_path=self._repo_path,
            branches=branches,
            branches_in_use=in_use,
            preselect_branch=preselect_branch,
            default_create_new=default_create,
            parent=self,
        )
        dlg.add_requested.connect(self._on_add_worktree_requested)
        dlg.switch_to_existing_requested.connect(self._switch_repo)
        dlg.exec()

    def _open_worktrees_dialog(self) -> None:
        if self._queries is None or self._commands is None:
            return
        from git_gui.presentation.dialogs.worktrees_dialog import WorktreesDialog

        try:
            wts = self._queries.list_worktrees.execute()
        except Exception as e:
            self._log_panel.log_error(f"Failed to list worktrees: {e}")
            return
        dlg = WorktreesDialog(worktrees=wts, parent=self)
        dlg.open_requested.connect(self._switch_repo)
        dlg.remove_requested.connect(self._begin_remove_worktree)
        dlg.lock_requested.connect(self._run_lock_worktree_with_reason)
        dlg.unlock_requested.connect(self._run_unlock_worktree)
        dlg.add_requested.connect(
            lambda: self._open_add_worktree_dialog(preselect_branch=None, default_create=False)
        )
        dlg.exec()

    def _on_add_worktree_requested(self, payload: dict) -> None:
        if self._commands is None:
            return
        signals = _WorktreeOpSignals(self)

        def _worker():
            try:
                wt = self._commands.add_worktree.execute(
                    payload["location"],
                    payload["branch"],
                    create_branch=payload["create_new"],
                    base_ref=payload["base_ref"],
                )
                signals.added.emit(str(wt.path), payload["switch_after"])
            except Exception as e:
                signals.failed.emit(str(e))

        signals.added.connect(self._on_worktree_added)
        signals.failed.connect(lambda msg: self._log_panel.log_error(f"Add worktree failed: {msg}"))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_worktree_added(self, path: str, switch_after: bool) -> None:
        self._load_worktrees_for_active_repo()
        if switch_after:
            self._switch_repo(path)

    def _run_lock_worktree_with_reason(self, path: str, reason: str) -> None:
        signals = _WorktreeOpSignals(self)

        def _worker():
            try:
                self._commands.lock_worktree.execute(path, reason=reason or None)
                signals.succeeded.emit()
            except Exception as e:
                signals.failed.emit(str(e))

        signals.succeeded.connect(self._load_worktrees_for_active_repo)
        signals.failed.connect(
            lambda msg: self._log_panel.log_error(f"Lock worktree failed: {msg}")
        )
        threading.Thread(target=_worker, daemon=True).start()

    def _run_lock_worktree(self, path: str) -> None:
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, "Lock Worktree", "Reason (optional):")
        if not ok:
            return
        self._run_lock_worktree_with_reason(path, text.strip())

    def _run_unlock_worktree(self, path: str) -> None:
        signals = _WorktreeOpSignals(self)

        def _worker():
            try:
                self._commands.unlock_worktree.execute(path)
                signals.succeeded.emit()
            except Exception as e:
                signals.failed.emit(str(e))

        signals.succeeded.connect(self._load_worktrees_for_active_repo)
        signals.failed.connect(
            lambda msg: self._log_panel.log_error(f"Unlock worktree failed: {msg}")
        )
        threading.Thread(target=_worker, daemon=True).start()

    def _begin_remove_worktree(self, path: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        if (
            QMessageBox.question(self, "Remove worktree", f"Remove worktree at {path}?")
            != QMessageBox.Yes
        ):
            return
        self._run_remove_worktree(path, force=False)

    def _run_remove_worktree(self, path: str, *, force: bool) -> None:
        signals = _WorktreeOpSignals(self)

        def _worker():
            try:
                self._commands.remove_worktree.execute(path, force=force)
                signals.succeeded.emit()
            except Exception as e:
                # Dispatch by class name to keep this layer infra-free
                # (the architecture guard forbids importing the concrete
                # error types here).
                name = type(e).__name__
                if name == "WorktreeDirtyError":
                    signals.dirty_error.emit(path)
                elif name == "WorktreeLockedError":
                    signals.locked_error.emit(path, str(e))
                else:
                    signals.failed.emit(str(e))

        signals.succeeded.connect(self._on_worktree_removed)
        signals.dirty_error.connect(self._on_remove_dirty)
        signals.locked_error.connect(self._on_remove_locked)
        signals.failed.connect(
            lambda msg: self._log_panel.log_error(f"Remove worktree failed: {msg}")
        )
        threading.Thread(target=_worker, daemon=True).start()

    def _on_worktree_removed(self) -> None:
        self._load_worktrees_for_active_repo()

    def _on_remove_dirty(self, path: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        msg = QMessageBox(self)
        msg.setWindowTitle("Worktree is dirty")
        msg.setText(f"The worktree at {path} has uncommitted changes.\nForce remove anyway?")
        force = msg.addButton("Force remove", QMessageBox.DestructiveRole)
        msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.exec()
        if msg.clickedButton() is force:
            self._run_remove_worktree(path, force=True)

    def _on_remove_locked(self, path: str, reason: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        msg = QMessageBox(self)
        msg.setWindowTitle("Worktree is locked")
        msg.setText(f"The worktree at {path} is locked.\n{reason}\n\nForce remove anyway?")
        force = msg.addButton("Force remove", QMessageBox.DestructiveRole)
        msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.exec()
        if msg.clickedButton() is force:
            self._run_remove_worktree(path, force=True)
