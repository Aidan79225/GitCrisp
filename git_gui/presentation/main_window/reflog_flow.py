# git_gui/presentation/main_window/reflog_flow.py
"""Reflog flow — opening the pane, and restoring a ref to an earlier state.

Mixin — not instantiable on its own. Relies on composite-provided attributes
set up by MainWindow's __init__.
"""

from __future__ import annotations

from git_gui.domain.entities import ResetMode
from git_gui.presentation.dialogs.reset_dialog import ResetDialog
from git_gui.presentation.widgets.reflog_pane import ReflogPane


class ReflogFlowMixin:
    def open_reflog(self) -> None:
        """Show where HEAD has been, in the commit list's column."""
        if self._queries is None:
            return
        if self._reflog_pane is not None:
            self._reflog_pane.setFocus()
            return
        self._close_blame_pane()

        pane = ReflogPane(self._queries)
        pane.commit_selected.connect(self._on_reflog_commit_selected)
        pane.restore_requested.connect(self._on_reflog_restore_requested)
        pane.close_requested.connect(self._close_reflog_pane)
        self._reflog_pane = pane
        self._left_stack.addWidget(pane)
        self._left_stack.setCurrentWidget(pane)
        self._splitter.setSizes(self._blame_sizes)
        pane.setFocus()

    def _on_reflog_commit_selected(self, oid: str) -> None:
        """Show the state a row points at, so it can be checked before restoring.

        Loaded straight into the diff pane rather than through the commit list,
        which is off screen — and which cannot show these commits at all once
        nothing references them.
        """
        self._selected_oid = oid
        self._right_stack.setCurrentIndex(0)
        self._diff.load_commit(oid)

    def _on_reflog_restore_requested(self, oid: str, entry_label: str) -> None:
        """Move the branch back to where it was before a reflog entry.

        This is a reset, so it runs through the same dialog every other reset
        does: restoring is exactly as destructive as the operation it undoes,
        and the uncommitted work it can discard deserves the same warning.
        """
        short = oid[:7]
        try:
            commit = self._queries.get_commit_detail.execute(oid)
            head_branch = self._queries.get_repo_state.execute().head_branch or "HEAD"
            dirty_files = self._queries.get_working_tree.execute()

            dlg = ResetDialog(
                branch_name=head_branch,
                short_sha=short,
                commit_subject=(commit.message.splitlines()[0] if commit.message else ""),
                default_mode=ResetMode.HARD,
                dirty_files=dirty_files,
                parent=self,
            )
            if dlg.exec() != ResetDialog.Accepted:
                return
            mode = dlg.result_mode()
            self._commands.reset_branch.execute(oid, mode)
            self._log_panel.log(
                f"Restore {head_branch} --{mode.value.lower()} to {short} (before {entry_label})"
            )
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Restore to {short} — ERROR: {e}")
            return

        # The reflog just grew an entry of its own, and the commit list has
        # moved; both need rereading before either is looked at again.
        self._close_reflog_pane()
        self._reload()

    def _close_reflog_pane(self) -> None:
        """Give the column back to the commit list."""
        pane = self._reflog_pane
        if pane is None:
            return
        self._reflog_pane = None
        self._left_stack.setCurrentIndex(0)
        self._left_stack.removeWidget(pane)
        pane.deleteLater()
        self._splitter.setSizes(self._graph_sizes)
