from __future__ import annotations


class ReloadCoordinatorMixin:
    """Central sync — fans out reloads to sidebar/graph and refreshes banners.

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__.
    """

    def _wire_reload_signals(self) -> None:
        self._working_tree.reload_requested.connect(self._reload)
        self._graph.reload_requested.connect(self._reload)
        self._graph.load_failed.connect(
            lambda reason: self._report_load_failure("Load commits", reason)
        )
        self._sidebar.load_failed.connect(
            lambda reason: self._report_load_failure("List branches and tags", reason)
        )

    def _report_load_failure(self, what: str, reason: str) -> None:
        # The pane that failed has been cleared, so this line is the only sign
        # of why — and a line added to the collapsed log is never seen.
        self._log_panel.expand()
        self._log_panel.log_error(f"{what} — ERROR: {reason}")

    def _reload(self) -> None:
        if getattr(self, "_change_detector", None) is not None:
            self._change_detector.notify_self_reload()
        if self._queries is None:
            return
        self._sidebar.reload()
        self._graph.reload()
        if self._reflog_pane is not None:
            self._reflog_pane.reload()
        if self._right_stack.currentIndex() == 1:
            self._working_tree.reload()
        self._refresh_state_banners()

    def _refresh_state_banners(self) -> None:
        """Show the open repo's merge/rebase state, or none, in both panes."""
        try:
            state_info = self._queries.get_repo_state.execute()
            state_name = state_info.state.name
            merge_msg = self._queries.get_merge_msg.execute() if state_name == "MERGING" else None
            self._working_tree.update_conflict_banner(state_name, merge_msg)
            self._diff.update_state_banner(state_name)
        except Exception:
            self._working_tree.update_conflict_banner("CLEAN")
            self._diff.update_state_banner("CLEAN")
