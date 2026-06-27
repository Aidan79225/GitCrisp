# git_gui/presentation/main_window/branch_flows.py
from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox


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
                    self._commands.checkout.execute(local_name)
                    self._commands.reset_branch_to_ref.execute(local_name, name)
                    self._log_panel.log(f"Reset {local_name} to {name}")
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
