# git_gui/presentation/main_window/cherry_pick_revert_flows.py
from __future__ import annotations


class CherryPickRevertFlowsMixin:
    """Cherry-pick and revert operations — apply, abort, continue.

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__.
    """

    def _wire_cherry_pick_revert_flow_signals(self) -> None:
        self._graph.cherry_pick_requested.connect(self._on_cherry_pick)
        self._graph.revert_commit_requested.connect(self._on_revert)
        self._diff.cherry_pick_abort_requested.connect(self._on_cherry_pick_abort)
        self._working_tree.cherry_pick_abort_requested.connect(self._on_cherry_pick_abort)
        self._diff.cherry_pick_continue_requested.connect(self._on_cherry_pick_continue)
        self._working_tree.cherry_pick_continue_requested.connect(self._on_cherry_pick_continue)
        self._diff.revert_abort_requested.connect(self._on_revert_abort)
        self._working_tree.revert_abort_requested.connect(self._on_revert_abort)
        self._diff.revert_continue_requested.connect(self._on_revert_continue)
        self._working_tree.revert_continue_requested.connect(self._on_revert_continue)

    def _on_cherry_pick(self, oid: str) -> None:
        short = oid[:7]
        head_before = self.head_before_operation()
        try:
            self._commands.cherry_pick.execute(oid)
            self._log_undoable(f"Cherry-pick: {short}", head_before)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Cherry-pick {short} — ERROR: {e}")
        self._reload()

    def _on_revert(self, oid: str) -> None:
        short = oid[:7]
        head_before = self.head_before_operation()
        try:
            self._commands.revert_commit.execute(oid)
            self._log_undoable(f"Revert: {short}", head_before)
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Revert {short} — ERROR: {e}")
        self._reload()

    def _on_cherry_pick_abort(self) -> None:
        try:
            self._commands.cherry_pick_abort.execute()
            self._log_panel.log("Cherry-pick aborted")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Cherry-pick abort — ERROR: {e}")
        self._reload()

    def _on_cherry_pick_continue(self) -> None:
        try:
            if self._queries.has_unresolved_conflicts.execute():
                self._log_panel.expand()
                self._log_panel.log_error("Resolve all conflicts and stage files first")
                return
            self._commands.cherry_pick_continue.execute()
            self._log_panel.log("Cherry-pick continued")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Cherry-pick continue — ERROR: {e}")
        self._reload()

    def _on_revert_abort(self) -> None:
        try:
            self._commands.revert_abort.execute()
            self._log_panel.log("Revert aborted")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Revert abort — ERROR: {e}")
        self._reload()

    def _on_revert_continue(self) -> None:
        try:
            if self._queries.has_unresolved_conflicts.execute():
                self._log_panel.expand()
                self._log_panel.log_error("Resolve all conflicts and stage files first")
                return
            self._commands.revert_continue.execute()
            self._log_panel.log("Revert continued")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Revert continue — ERROR: {e}")
        self._reload()
