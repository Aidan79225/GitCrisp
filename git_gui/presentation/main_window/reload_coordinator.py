from __future__ import annotations

import logging

from git_gui.domain.entities import RepoState

logger = logging.getLogger(__name__)


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
        state = self._read_repo_state()
        merge_msg = self._read_merge_msg() if state is RepoState.MERGING else None
        self._working_tree.update_conflict_banner(state.name, merge_msg)
        self._diff.update_state_banner(state.name)

    def _read_repo_state(self) -> RepoState:
        try:
            return self._queries.get_repo_state.execute().state
        except Exception as e:
            logger.warning("Reading the repo state failed: %s", e)
            return RepoState.CLEAN

    def _read_merge_msg(self) -> str | None:
        # Read apart from the state: a merge whose message cannot be read is
        # still a merge, and showing it as clean would hide Abort and offer Amend.
        try:
            return self._queries.get_merge_msg.execute()
        except Exception as e:
            logger.warning("Reading the merge message failed: %s", e)
            return None
