# git_gui/presentation/main_window/merge_rebase_flows.py
from __future__ import annotations

from git_gui.presentation.dialogs.interactive_rebase_dialog import InteractiveRebaseDialog
from git_gui.presentation.dialogs.merge_dialog import MergeDialog


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
        try:
            all_branches = self._queries.get_branches.execute()
            target = None
            for b in all_branches:
                if b.name == branch:
                    target = b
                    break
            if not target:
                self._log_panel.log_error(f"Branch not found: {branch}")
                return
            analysis = self._queries.get_merge_analysis.execute(target.target_oid)
            head_branch = self._queries.get_repo_state.execute().head_branch or "HEAD"
            default_msg = f"Merge branch '{branch}'"

            if analysis.is_up_to_date:
                self._log_panel.log(f"Merge {branch}: already up to date")
                return

            dlg = MergeDialog(branch, head_branch, analysis.can_ff, default_msg, parent=self)
            if dlg.exec() != MergeDialog.Accepted:
                return
            req = dlg.result_value()
            head_before = self.head_before_operation()
            self._commands.merge.execute(branch, strategy=req.strategy, message=req.message)
            self._log_undoable(f"Merge: {branch} into {head_branch}", head_before)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Merge {branch} — ERROR: {e}")
        self._reload()

    def _on_rebase(self, branch: str) -> None:
        head_before = self.head_before_operation()
        try:
            self._commands.rebase.execute(branch)
            self._log_undoable(f"Rebase onto {branch}", head_before)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Rebase onto {branch} — ERROR: {e}")
        self._reload()

    def _on_merge_commit(self, oid: str) -> None:
        try:
            analysis = self._queries.get_merge_analysis.execute(oid)
            head_branch = self._queries.get_repo_state.execute().head_branch or "HEAD"
            short_oid = oid[:7]
            default_msg = f"Merge commit {short_oid}"

            if analysis.is_up_to_date:
                self._log_panel.log(f"Merge commit {short_oid}: already up to date")
                return

            dlg = MergeDialog(
                f"commit {short_oid}", head_branch, analysis.can_ff, default_msg, parent=self
            )
            if dlg.exec() != MergeDialog.Accepted:
                return
            req = dlg.result_value()
            head_before = self.head_before_operation()
            self._commands.merge_commit.execute(oid, strategy=req.strategy, message=req.message)
            self._log_undoable(f"Merge: commit {short_oid} into {head_branch}", head_before)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Merge commit {short_oid} — ERROR: {e}")
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
            all_branches = self._queries.get_branches.execute()
            target = None
            for b in all_branches:
                if b.name == branch:
                    target = b
                    break
            if not target:
                self._log_panel.log_error(f"Branch not found: {branch}")
                return
            self._open_interactive_rebase(target.target_oid, branch)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Interactive rebase — ERROR: {e}")

    def _on_interactive_rebase_commit(self, oid: str) -> None:
        self._open_interactive_rebase(oid, f"commit {oid[:7]}")

    def _open_interactive_rebase(self, target_oid: str, target_label: str) -> None:
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
                f"Interactive rebase onto {target_label}",
                lambda: self._commands.interactive_rebase.execute(target_oid, entries),
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
