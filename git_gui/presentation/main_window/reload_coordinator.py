# git_gui/presentation/main_window/reload_coordinator.py
from __future__ import annotations


class ReloadCoordinatorMixin:
    """Central sync — fans out reloads to sidebar/graph and refreshes banners.

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__.
    """

    def _wire_reload_signals(self) -> None:
        self._working_tree.reload_requested.connect(self._reload)
        self._graph.reload_requested.connect(self._reload)

    def _reload(self) -> None:
        if getattr(self, "_change_detector", None) is not None:
            self._change_detector.notify_self_reload()
        if self._queries is None:
            return
        self._sidebar.reload()
        self._graph.reload()
        if self._right_stack.currentIndex() == 1:
            self._working_tree.reload()
        if self._queries is not None:
            try:
                state_info = self._queries.get_repo_state.execute()
                state_name = state_info.state.name
                merge_msg = (
                    self._queries.get_merge_msg.execute() if state_name == "MERGING" else None
                )
                self._working_tree.update_conflict_banner(state_name, merge_msg)
                self._diff.update_state_banner(state_name)
            except Exception:
                self._working_tree.update_conflict_banner("CLEAN")
                self._diff.update_state_banner("CLEAN")
