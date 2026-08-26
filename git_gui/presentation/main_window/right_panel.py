# git_gui/presentation/main_window/right_panel.py
from __future__ import annotations

from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.presentation.widgets.clone_dialog import CloneDialog
from git_gui.presentation.widgets.insight_dialog import InsightDialog


class RightPanelMixin:
    """Right-pane orchestration — commit/working-tree stack, insight, clone, submodules.

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__.
    """

    def _wire_right_panel_signals(self) -> None:
        self._graph.commit_selected.connect(self._on_commit_selected)
        self._working_tree.working_tree_empty.connect(self._on_working_tree_empty)
        self._graph.insight_requested.connect(self._on_insight_requested)
        self._repo_list.clone_requested.connect(self._on_clone_requested)
        self._diff.submodule_open_requested.connect(self._on_submodule_path_clicked)
        self._working_tree.submodule_open_requested.connect(self._on_submodule_path_clicked)
        self._graph.path_filter_changed.connect(self._diff.set_path_filter)
        self._working_tree.file_history_requested.connect(self._on_file_history_requested)
        self._diff.file_history_requested.connect(self._on_file_history_requested)

    def _on_commit_selected(self, oid: str) -> None:
        self._sidebar.clear_stash_selection()
        self._selected_oid = oid
        if oid == WORKING_TREE_OID:
            self._right_stack.setCurrentIndex(1)
            self._working_tree.reload()
        else:
            self._right_stack.setCurrentIndex(0)
            self._diff.load_commit(oid)

    def _on_file_history_requested(self, path: str) -> None:
        """Filter the commit list to one file's history."""
        self._graph.set_path_filter(path)

    def _on_working_tree_empty(self) -> None:
        """Working tree has no changes — switch back to commit info and refresh graph."""
        self._graph.reload()
        oid = self._selected_oid
        if not oid or oid == WORKING_TREE_OID:
            if self._queries:
                oid = self._queries.get_head_oid.execute()
        if oid and oid != WORKING_TREE_OID:
            self._right_stack.setCurrentIndex(0)
            self._diff.load_commit(oid)

    def _on_insight_requested(self) -> None:
        if self._queries is None:
            return
        dialog = InsightDialog(self._queries, self)
        dialog.exec()

    def _on_clone_requested(self) -> None:
        dialog = CloneDialog(self)
        dialog.clone_completed.connect(self._on_clone_completed)
        dialog.exec()

    def _on_clone_completed(self, path: str) -> None:
        self._repo_store.add_open(path)
        self._repo_store.save()
        self._switch_repo(path)
        self._log_panel.log(f"Cloned repository: {path}")

    def _on_submodule_open_requested(self, abs_path: str) -> None:
        """Open a submodule as a top-level repo (one-way switch).

        Inserts the submodule right after the current (parent) repo in the
        open list, so the sidebar shows submodules grouped under their parent.
        """
        self._repo_store.add_open(abs_path, after=self._repo_path)
        self._repo_store.save()
        self._switch_repo(abs_path)

    def _on_submodule_path_clicked(self, rel_path: str) -> None:
        """Resolve a relative submodule path against the current repo and open it."""
        if not self._repo_path:
            return
        import os

        abs_path = os.path.abspath(os.path.join(self._repo_path, rel_path))
        self._on_submodule_open_requested(abs_path)
