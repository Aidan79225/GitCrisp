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
    def _wire_reflog_signals(self) -> None:
        self._log_panel.action_triggered.connect(self._on_log_action)
        # The toolbar is not only for what you press often; it is also where the
        # app says what it is for. Getting back from a mistake is one of those
        # things, so it gets a button as well as its menu entry.
        self._graph.reflog_requested.connect(self.open_reflog)

    def head_before_operation(self) -> str | None:
        """Where HEAD is right now, to be offered back if the next step is wrong."""
        if self._queries is None:
            return None
        try:
            return self._queries.get_head_oid.execute()
        except Exception:
            return None

    def _log_undoable(self, message: str, head_before: str | None) -> None:
        """Log an operation, with an Undo returning HEAD to where it started.

        The oid is captured before the operation rather than read back from the
        reflog when the link is clicked: it names the state the user was
        actually in, and stays right even if something else moves HEAD in
        between. Reading `HEAD@{1}` at click time would undo whatever happened
        most recently instead of what this line reports.
        """
        if not head_before:
            self._log_panel.log(message)
            return
        self._undoable[head_before] = message
        self._log_panel.log_action(message, "Undo", head_before)

    def _on_log_action(self, action_id: str) -> None:
        message = self._undoable.get(action_id)
        if message is None:
            return
        # Same path as restoring from the pane: an undo is a reset, and is as
        # destructive as whatever it undoes.
        self._on_reflog_restore_requested(action_id, message)

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
