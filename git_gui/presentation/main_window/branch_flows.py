# git_gui/presentation/main_window/branch_flows.py
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox

from git_gui.domain.entities import Branch
from git_gui.presentation.dialogs.branch_select_dialog import BranchSelectDialog


class BranchFlowsMixin:
    """Branch operations — checkout, create, delete, and commit checkout.

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__.
    """

    def _wire_branch_flow_signals(self) -> None:
        self._sidebar.checkout_branch_requested.connect(self._on_checkout_branch)
        self._sidebar.branch_delete_requested.connect(self._on_delete_branch)
        self._sidebar.remote_branch_delete_requested.connect(self._on_delete_remote_branch)
        self._graph.remote_branch_delete_requested.connect(self._on_delete_remote_branch)
        self._graph.delete_branch_requested.connect(self._on_delete_branch)
        self._graph.create_branch_requested.connect(self._on_create_branch)
        self._graph.checkout_commit_requested.connect(self._on_checkout_commit)
        self._graph.checkout_branch_requested.connect(self._on_checkout_branch)
        self._graph.commit_double_clicked.connect(self._on_commit_double_clicked)

    def _on_delete_branch(self, branch: str) -> None:
        # git refuses to delete a branch that is checked out in a linked
        # worktree. When that's the case, offer to remove the worktree first
        # (instead of surfacing libgit2's opaque "current HEAD of a linked
        # repository" error).
        wt = self._linked_worktree_for_branch(branch)
        if wt is not None and not self._remove_worktree_for_branch_delete(branch, wt):
            return
        try:
            self._commands.delete_branch.execute(branch)
            self._log_panel.log(f"Deleted branch: {branch}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Delete branch {branch} — ERROR: {e}")
        self._reload()

    def _linked_worktree_for_branch(self, branch: str):
        """Return the linked (non-main) worktree that has `branch` checked out,
        or None. The main worktree is excluded — it can't be removed."""
        if self._queries is None:
            return None
        try:
            wt = self._queries.find_worktree_for_branch.execute(branch)
        except Exception:
            return None
        if wt is None or wt.is_main:
            return None
        return wt

    def _remove_worktree_for_branch_delete(self, branch: str, wt) -> bool:
        """Confirm and remove the worktree holding `branch`. Returns True if it
        was removed (so deletion can proceed), False to abort."""
        reply = QMessageBox.question(
            self,
            "Branch in use by a worktree",
            f"Branch '{branch}' is checked out in the worktree:\n{wt.path}\n\n"
            "Remove the worktree and delete the branch?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return False

        force = False
        while True:
            try:
                self._commands.remove_worktree.execute(wt.path, force=force)
                self._log_panel.log(f"Removed worktree: {wt.path}")
                self._load_worktrees_for_active_repo()
                return True
            except Exception as e:
                # Dispatch by class name to keep this layer infra-free (the
                # architecture guard forbids importing the concrete errors).
                name = type(e).__name__
                if not force and name in ("WorktreeDirtyError", "WorktreeLockedError"):
                    detail = (
                        "has uncommitted changes" if name == "WorktreeDirtyError" else "is locked"
                    )
                    if self._ask_force_remove_worktree(wt.path, detail):
                        force = True
                        continue
                    return False
                self._log_panel.expand()
                self._log_panel.log_error(f"Remove worktree {wt.path} — ERROR: {e}")
                return False

    def _ask_force_remove_worktree(self, path: str, detail: str) -> bool:
        msg = QMessageBox(self)
        msg.setWindowTitle("Force remove worktree?")
        msg.setText(f"The worktree {path} {detail}.\nForce remove anyway?")
        force_btn = msg.addButton("Force remove", QMessageBox.DestructiveRole)
        msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.exec()
        return msg.clickedButton() is force_btn

    def _on_delete_remote_branch(self, remote: str, branch: str) -> None:
        reply = QMessageBox.question(
            self,
            "Delete Remote Branch",
            f"Delete remote branch `{remote}/{branch}`? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._run_remote_op(
            f"Delete {remote}/{branch}",
            lambda: self._commands.delete_remote_branch.execute(remote, branch),
        )

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
            all_branches = self._queries.get_branches.execute()
            local_names = {b.name for b in all_branches if not b.is_remote}

            if name in local_names:
                self._commands.checkout.execute(name)
                self._log_panel.log(f"Checkout branch: {name}")
            else:
                local_name = name.split("/", 1)[1] if "/" in name else name
                if local_name in local_names:
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
                    head_before = self.head_before_operation()
                    self._commands.checkout.execute(local_name)
                    self._commands.reset_branch_to_ref.execute(local_name, name)
                    self._log_undoable(f"Reset {local_name} to {name}", head_before)
                else:
                    self._commands.checkout_remote_branch.execute(name)
                    self._log_panel.log(f"Checkout remote: {name} → local {local_name}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Checkout {name} — ERROR: {e}")
        self._reload()
        if self._queries is not None:
            head_oid = self._queries.get_head_oid.execute()
            if head_oid:
                self._graph.scroll_to_oid(head_oid, select=True)

    # ── Double-click to switch branch ───────────────────────────────────

    def _on_commit_double_clicked(self, oid: str) -> None:
        """Switch to a branch pointing at the double-clicked commit.

        - No branch on the commit → do nothing.
        - Exactly one branch → check it out directly.
        - Several branches → let the user pick one via a dialog.

        Local branches take precedence: when a commit carries both a local
        branch and its remote-tracking counterpart, we offer the local one
        (switching to a remote-only branch is handled by the remote path in
        `_on_checkout_branch`). After checking out a local branch we offer to
        reset it to its remote when the two have diverged.
        """
        if self._queries is None or not oid:
            return
        try:
            all_branches = self._queries.get_branches.execute()
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"List branches — ERROR: {e}")
            return

        on_commit = [b for b in all_branches if b.target_oid == oid]
        local = [b for b in on_commit if not b.is_remote]
        remote = [b for b in on_commit if b.is_remote]
        # Prefer local branches; fall back to remote-only branches on the commit.
        candidates = local or remote
        if not candidates:
            return

        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            names = [b.name for b in candidates]
            dlg = BranchSelectDialog(names, parent=self)
            if dlg.exec() != QDialog.Accepted:
                return
            picked = dlg.selected()
            chosen = next((b for b in candidates if b.name == picked), None)
            if chosen is None:
                return

        self._switch_to_branch(chosen, all_branches)

    def _switch_to_branch(self, branch: Branch, all_branches: list[Branch]) -> None:
        if branch.is_remote:
            # Remote-only branch on this commit — reuse the existing dispatch,
            # which creates/updates the tracking local branch as needed.
            self._on_checkout_branch(branch.name)
            return
        try:
            self._commands.checkout.execute(branch.name)
            self._log_panel.log(f"Checkout branch: {branch.name}")
            self._offer_reset_to_remote_if_diverged(branch, all_branches)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Checkout {branch.name} — ERROR: {e}")
        self._reload()
        if self._queries is not None:
            head_oid = self._queries.get_head_oid.execute()
            if head_oid:
                self._graph.scroll_to_oid(head_oid, select=True)

    def _offer_reset_to_remote_if_diverged(
        self, branch: Branch, all_branches: list[Branch]
    ) -> None:
        """When a just-checked-out local branch differs from its upstream,
        offer to hard-reset it to the remote."""
        upstream = self._upstream_for(branch.name)
        if not upstream:
            return
        remote_oid = next(
            (b.target_oid for b in all_branches if b.is_remote and b.name == upstream),
            None,
        )
        if remote_oid is None or remote_oid == branch.target_oid:
            return  # No upstream ref loaded, or already in sync.

        reply = QMessageBox.question(
            self,
            "Local branch differs from remote",
            f"Local '{branch.name}' differs from '{upstream}'.\n\n"
            f"Reset '{branch.name}' to '{upstream}'? This discards any local "
            f"commits and uncommitted changes on '{branch.name}'.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        head_before = self.head_before_operation()
        self._commands.reset_branch_to_ref.execute(branch.name, upstream)
        self._log_undoable(f"Reset {branch.name} to {upstream}", head_before)

    def _upstream_for(self, name: str) -> str | None:
        """Return the upstream (remote-tracking) shorthand for a local branch,
        e.g. 'origin/main', or None when it has no upstream."""
        if self._queries is None:
            return None
        try:
            for info in self._queries.list_local_branches_with_upstream.execute():
                if info.name == name:
                    return info.upstream
        except Exception:
            return None
        return None
