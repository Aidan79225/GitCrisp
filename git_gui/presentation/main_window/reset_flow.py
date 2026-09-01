# git_gui/presentation/main_window/reset_flow.py
from __future__ import annotations

from git_gui.domain.entities import ResetMode
from git_gui.presentation.dialogs.reset_dialog import ResetDialog


class ResetFlowMixin:
    """Reset-to-commit flow — dialog, command dispatch, logging.

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__.
    """

    def _wire_reset_flow_signals(self) -> None:
        self._graph.reset_to_commit_requested.connect(self._on_reset_to_commit)

    def _on_reset_to_commit(self, oid: str, default_mode: ResetMode) -> None:
        short = oid[:7]
        head_before = self.head_before_operation()
        try:
            commit = self._queries.get_commit_detail.execute(oid)
            head_branch = self._queries.get_repo_state.execute().head_branch or "HEAD"
            dirty_files = self._queries.get_working_tree.execute()

            dlg = ResetDialog(
                branch_name=head_branch,
                short_sha=short,
                commit_subject=(commit.message.splitlines()[0] if commit.message else ""),
                default_mode=default_mode,
                dirty_files=dirty_files,
                parent=self,
            )
            if dlg.exec() != ResetDialog.Accepted:
                return
            mode = dlg.result_mode()
            self._commands.reset_branch.execute(oid, mode)
            self._log_undoable(
                f"Reset {head_branch} --{mode.value.lower()} to {short}", head_before
            )
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Reset to {short} — ERROR: {e}")
        self._reload()
