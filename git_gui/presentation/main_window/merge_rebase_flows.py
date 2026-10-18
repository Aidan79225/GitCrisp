from __future__ import annotations

from collections.abc import Callable

from git_gui.presentation.dialogs.identity_dialog import ensure_identity
from git_gui.presentation.dialogs.interactive_rebase_dialog import InteractiveRebaseDialog
from git_gui.presentation.dialogs.merge_dialog import MergeDialog, MergeRequest


class MergeRebaseFlowsMixin:
    """Merge and rebase operations — merge, rebase, interactive rebase,
    abort/continue for both, plus the shared interactive-rebase helper.

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__.
    """

    def _wire_merge_rebase_flow_signals(self) -> None:
        self._working_tree.merge_abort_requested.connect(self._on_merge_abort)
        self._working_tree.rebase_abort_requested.connect(self._on_rebase_abort)
        self._working_tree.merge_continue_requested.connect(self._on_merge_continue)
        self._working_tree.rebase_continue_requested.connect(self._on_rebase_continue)
        self._diff.merge_abort_requested.connect(self._on_merge_abort)
        self._diff.rebase_abort_requested.connect(self._on_rebase_abort)
        self._diff.rebase_continue_requested.connect(lambda: self._on_rebase_continue(""))
        self._sidebar.branch_merge_requested.connect(self._on_merge)
        self._sidebar.branch_rebase_requested.connect(self._on_rebase)
        self._graph.merge_branch_requested.connect(self._on_merge)
        self._graph.merge_commit_requested.connect(self._on_merge_commit)
        self._graph.rebase_onto_branch_requested.connect(self._on_rebase)
        self._graph.rebase_onto_commit_requested.connect(self._on_rebase_onto_commit)
        self._graph.interactive_rebase_branch_requested.connect(self._on_interactive_rebase_branch)
        self._graph.interactive_rebase_commit_requested.connect(self._on_interactive_rebase_commit)

    def _on_merge(self, branch: str) -> None:
        self._merge_into_head(
            branch,
            f"Merge branch '{branch}'",
            resolve_target=lambda: self._tip_of_branch(branch),
            run=lambda req: self._commands.merge.execute(
                branch, strategy=req.strategy, message=req.message
            ),
        )

    def _on_merge_commit(self, oid: str) -> None:
        label = f"commit {oid[:7]}"
        self._merge_into_head(
            label,
            f"Merge {label}",
            resolve_target=lambda: oid,
            run=lambda req: self._commands.merge_commit.execute(
                oid, strategy=req.strategy, message=req.message
            ),
        )

    def _merge_into_head(
        self,
        label: str,
        default_message: str,
        *,
        resolve_target: Callable[[], str | None],
        run: Callable[[MergeRequest], object],
    ) -> None:
        """Merge the commit *resolve_target* finds into HEAD once the user
        confirms it in the merge dialog. *label* names the target in the log."""
        try:
            target_oid = resolve_target()
            if target_oid is None:
                return
            analysis = self._queries.get_merge_analysis.execute(target_oid)
            head_branch = self._queries.get_repo_state.execute().head_branch or "HEAD"
            if analysis.is_up_to_date:
                self._log_panel.log(f"Merge {label}: already up to date")
                return
            req = self._ask_merge(label, head_branch, analysis.can_ff, default_message)
            if req is None:
                return
            head_before = self.head_before_operation()
            run(req)
            self._log_undoable(f"Merge: {label} into {head_branch}", head_before)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Merge {label} — ERROR: {e}")
        self._reload()

    def _ask_merge(
        self, label: str, head_branch: str, can_ff: bool, default_message: str
    ) -> MergeRequest | None:
        """The merge the user chose in the dialog, or None if they cancelled
        or have no git identity to sign it with."""
        dlg = MergeDialog(label, head_branch, can_ff, default_message, parent=self)
        if dlg.exec() != MergeDialog.Accepted:
            return None
        if not ensure_identity(self, self._queries, self._commands):
            return None
        return dlg.result_value()

    def _tip_of_branch(self, name: str) -> str | None:
        """The commit branch *name* points at, or None (reported) if there is
        no such branch."""
        target = next((b for b in self._queries.get_branches.execute() if b.name == name), None)
        if target is None:
            self._log_panel.log_error(f"Branch not found: {name}")
            return None
        return target.target_oid

    def _on_rebase(self, branch: str) -> None:
        head_before = self.head_before_operation()
        try:
            self._commands.rebase.execute(branch)
            self._log_undoable(f"Rebase onto {branch}", head_before)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Rebase onto {branch} — ERROR: {e}")
        self._reload()

    def _on_rebase_onto_commit(self, oid: str) -> None:
        head_before = self.head_before_operation()
        try:
            self._commands.rebase_onto_commit.execute(oid)
            self._log_undoable(f"Rebase onto commit {oid[:7]}", head_before)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Rebase onto commit {oid[:7]} — ERROR: {e}")
        self._reload()

    def _on_interactive_rebase_branch(self, branch: str) -> None:
        try:
            target_oid = self._tip_of_branch(branch)
            if target_oid is not None:
                self._open_interactive_rebase(target_oid, branch)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Interactive rebase — ERROR: {e}")

    def _on_interactive_rebase_commit(self, oid: str) -> None:
        self._open_interactive_rebase(oid, f"commit {oid[:7]}")

    def _open_interactive_rebase(self, target_oid: str, target_label: str) -> None:
        op_name = f"Interactive rebase onto {target_label}"
        # The rebase runs in the remote-op slot: check it before the user
        # edits a plan, not after.
        if self._remote_slot_busy(op_name):
            return
        commands = self._commands
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
                op_name,
                lambda: commands.interactive_rebase.execute(target_oid, entries),
                commands=commands,
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
