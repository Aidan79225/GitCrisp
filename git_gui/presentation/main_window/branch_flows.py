from __future__ import annotations

import logging

from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox

from git_gui.domain.entities import Branch, StagingState, Worktree
from git_gui.presentation.bus import CommandBus
from git_gui.presentation.dialogs.branch_select_dialog import BranchSelectDialog
from git_gui.presentation.main_window.asked_repo_guard import AskedRepoGuardMixin

logger = logging.getLogger(__name__)


class BranchFlowsMixin(AskedRepoGuardMixin):
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
        commands = self._commands
        wt = self._linked_worktree_for_branch(branch)
        if wt is not None:
            if not self._remove_worktree_for_branch_delete(branch, wt, commands):
                return
        elif not self._confirm_delete_branch(branch):
            return
        elif self._repo_switched_while_asking(commands, f"Delete branch {branch}"):
            return
        try:
            commands.delete_branch.execute(branch)
            self._log_panel.log(f"Deleted branch: {branch}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Delete branch {branch} — ERROR: {e}")
        self._reload()

    def _confirm_delete_branch(self, branch: str) -> bool:
        reply = QMessageBox.question(
            self,
            "Delete branch",
            f"Delete branch '{branch}'? Commits that are only on it will be lost.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

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

    def _remove_worktree_for_branch_delete(self, branch: str, wt, commands: CommandBus) -> bool:
        """Confirm and remove the worktree holding `branch`. Returns True if it
        was removed (so deletion can proceed), False to abort."""
        op_name = f"Remove worktree {wt.path}"
        reply = QMessageBox.question(
            self,
            "Branch in use by a worktree",
            f"Branch '{branch}' is checked out in the worktree:\n{wt.path}\n\n"
            "Remove the worktree and delete the branch?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes or self._repo_switched_while_asking(commands, op_name):
            return False

        force = False
        while True:
            try:
                commands.remove_worktree.execute(wt.path, force=force)
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
                    if not self._ask_force_remove_worktree(wt.path, detail):
                        return False
                    if self._repo_switched_while_asking(commands, op_name):
                        return False
                    force = True
                    continue
                self._log_panel.expand()
                self._log_panel.log_error(f"{op_name} — ERROR: {e}")
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
        op_name = f"Delete {remote}/{branch}"
        if self._remote_slot_busy(op_name):
            return
        commands = self._commands
        reply = QMessageBox.question(
            self,
            "Delete Remote Branch",
            f"Delete remote branch `{remote}/{branch}`? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes or self._repo_switched_while_asking(commands, op_name):
            return
        self._run_remote_op(
            op_name,
            lambda: commands.delete_remote_branch.execute(remote, branch),
            commands=commands,
        )

    def _on_create_branch(self, oid: str) -> None:
        commands = self._commands
        name, ok = QInputDialog.getText(self, "Create Branch", "Branch name:")
        if not ok or not name.strip():
            return
        branch_name = name.strip()
        if self._repo_switched_while_asking(commands, f"Create branch {branch_name}"):
            return
        try:
            commands.create_branch.execute(branch_name, oid)
            commands.checkout.execute(branch_name)
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
            local_branches = {b.name: b for b in all_branches if not b.is_remote}

            if name in local_branches:
                if self._switch_to_worktree_holding(local_branches[name]):
                    return
                self._commands.checkout.execute(name)
                self._log_panel.log(f"Checkout branch: {name}")
            else:
                local_name = name.split("/", 1)[1] if "/" in name else name
                if local_name in local_branches:
                    if not self._reset_local_to_remote(local_branches[local_name], name):
                        return
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

    def _reset_local_to_remote(self, local: Branch, remote: str) -> bool:
        """Check out `local` and hard-reset it to `remote`, once the user
        agrees. Returns False when nothing was changed."""
        op_name = f"Reset {local.name} to {remote}"
        commands = self._commands
        if self._switch_to_worktree_holding(local):
            return False
        if self._carries_changes_from_another_branch(local):
            self._log_panel.expand()
            self._log_panel.log_error(
                f"{op_name} — skipped: it would discard your "
                "uncommitted changes. Commit or stash them first."
            )
            return False
        reply = QMessageBox.question(
            self,
            "Local branch exists",
            f"Local branch '{local.name}' already exists.\n\n"
            f"Reset it to '{remote}' (HEAD)? This discards any local "
            f"commits and uncommitted changes on '{local.name}'.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes or self._repo_switched_while_asking(commands, op_name):
            return False
        commands.checkout.execute(local.name)
        commands.reset_branch_to_ref.execute(local.name, remote)
        # Undo returns the reset branch to its own tip; HEAD may have been on
        # a different branch when this started.
        self._log_undoable(op_name, local.target_oid)
        return True

    def _carries_changes_from_another_branch(self, branch: Branch) -> bool:
        """Whether the working tree holds uncommitted edits made on a branch
        other than `branch`, which checking it out carries along and a hard
        reset of it would then destroy.

        `branch` must be as listed before any checkout, so that `is_head` says
        whether the edits were made on it. Untracked files do not count: a
        hard reset leaves them alone.
        """
        if branch.is_head:
            return False
        changes = self._queries.get_working_tree.execute()
        return any(f.status != StagingState.UNTRACKED for f in changes)

    def _switch_to_worktree_holding(self, branch: Branch) -> bool:
        """Open the worktree that has `branch` checked out, in place of
        checking it out here. Returns True when it did.

        This has to be asked before checking out rather than after it fails:
        libgit2 rewrites the working tree and index first, and only then
        refuses to move HEAD onto a branch another worktree holds, which
        leaves this worktree's files on one branch and its HEAD on another.
        """
        wt = self._worktree_holding_elsewhere(branch)
        if wt is None:
            return False
        self._log_panel.log(
            f"Branch {branch.name} is checked out in {wt.path} — switching to that worktree"
        )
        self._switch_repo(wt.path)
        return True

    def _worktree_holding_elsewhere(self, branch: Branch) -> Worktree | None:
        if branch.is_head or self._queries is None:
            return None
        try:
            return self._queries.find_worktree_for_branch.execute(branch.name)
        except Exception as e:
            logger.warning("Looking up the worktree for %s failed: %s", branch.name, e)
            return None

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
        commands = self._commands
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

        if self._repo_switched_while_asking(commands, f"Checkout {chosen.name}"):
            return
        self._switch_to_branch(chosen, all_branches)

    def _switch_to_branch(self, branch: Branch, all_branches: list[Branch]) -> None:
        if branch.is_remote:
            # Remote-only branch on this commit — reuse the existing dispatch,
            # which creates/updates the tracking local branch as needed.
            self._on_checkout_branch(branch.name)
            return
        if self._switch_to_worktree_holding(branch):
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
        commands = self._commands
        upstream = self._upstream_for(branch.name)
        if not upstream:
            return
        remote_oid = next(
            (b.target_oid for b in all_branches if b.is_remote and b.name == upstream),
            None,
        )
        if remote_oid is None or remote_oid == branch.target_oid:
            return  # No upstream ref loaded, or already in sync.
        if self._carries_changes_from_another_branch(branch):
            self._log_panel.log(
                f"'{branch.name}' differs from '{upstream}' — commit or stash your "
                "uncommitted changes to reset it"
            )
            return

        reply = QMessageBox.question(
            self,
            "Local branch differs from remote",
            f"Local '{branch.name}' differs from '{upstream}'.\n\n"
            f"Reset '{branch.name}' to '{upstream}'? This discards any local "
            f"commits and uncommitted changes on '{branch.name}'.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        op_name = f"Reset {branch.name} to {upstream}"
        if reply != QMessageBox.Yes or self._repo_switched_while_asking(commands, op_name):
            return
        head_before = self.head_before_operation()
        commands.reset_branch_to_ref.execute(branch.name, upstream)
        self._log_undoable(op_name, head_before)

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
