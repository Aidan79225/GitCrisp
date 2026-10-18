from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from git_gui.presentation.dialogs.identity_dialog import ensure_identity
from git_gui.presentation.main_window.asked_repo_guard import AskedRepoGuardMixin


class StashFlowsMixin(AskedRepoGuardMixin):
    """Stash operations — pop, apply, drop, create, and clicked preview.

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__.
    """

    def _wire_stash_flow_signals(self) -> None:
        self._sidebar.stash_pop_requested.connect(self._on_stash_pop)
        self._sidebar.stash_apply_requested.connect(self._on_stash_apply)
        self._sidebar.stash_drop_requested.connect(self._on_stash_drop)
        self._sidebar.stash_clicked.connect(self._on_stash_clicked)
        self._graph.stash_requested.connect(self._on_stash_requested)

    def _on_stash_pop(self, index: int) -> None:
        try:
            self._commands.pop_stash.execute(index)
            self._log_panel.log(f"Stash pop: @{{{index}}}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Stash pop @{{{index}}} — ERROR: {e}")
        self._reload()

    def _on_stash_apply(self, index: int) -> None:
        try:
            self._commands.apply_stash.execute(index)
            self._log_panel.log(f"Stash apply: @{{{index}}}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Stash apply @{{{index}}} — ERROR: {e}")
        self._reload()

    def _on_stash_drop(self, index: int) -> None:
        op_name = f"Stash drop @{{{index}}}"
        commands = self._commands
        reply = QMessageBox.question(
            self,
            "Drop Stash",
            f"Drop stash@{{{index}}}? Its changes will be lost.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes or self._repo_switched_while_asking(commands, op_name):
            return
        try:
            commands.drop_stash.execute(index)
            self._log_panel.log(f"Stash drop: @{{{index}}}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"{op_name} — ERROR: {e}")
        self._reload()

    def _on_stash_requested(self) -> None:
        commands = self._commands
        result = QMessageBox.question(
            self,
            "Stash Changes",
            "Would you like to stash all uncommitted changes?\n\n"
            "This will save your modifications and revert the working directory to a clean state.",
        )
        if result != QMessageBox.Yes:
            return
        if not ensure_identity(self, self._queries, self._commands):
            return
        if self._repo_switched_while_asking(commands, "Stash"):
            return
        branch = self._get_current_branch() or "unknown"
        try:
            commands.stash.execute(f"WIP on {branch}")
            self._log_panel.log(f"Stash: WIP on {branch}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Stash — ERROR: {e}")
        self._reload()

    def _on_stash_clicked(self, oid: str) -> None:
        self._graph.clear_selection()
        self._right_stack.setCurrentIndex(0)
        self._diff.load_commit(oid)
