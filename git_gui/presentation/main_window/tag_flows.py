# git_gui/presentation/main_window/tag_flows.py
from __future__ import annotations

import logging

from PySide6.QtWidgets import QDialog, QMessageBox

from git_gui.presentation.widgets.create_tag_dialog import CreateTagDialog

logger = logging.getLogger(__name__)


class TagFlowsMixin:
    """Tag operations — create and delete (local and/or remote).

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__.
    """

    def _wire_tag_flow_signals(self) -> None:
        self._graph.create_tag_requested.connect(self._on_create_tag)
        self._sidebar.tag_delete_requested.connect(self._on_delete_tag)

    def _on_create_tag(self, oid: str) -> None:
        dialog = CreateTagDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        name = dialog.tag_name()
        message = dialog.tag_message()
        try:
            self._commands.create_tag.execute(name, oid, message)
            kind = "annotated" if message else "lightweight"
            self._log_panel.log(f"Created {kind} tag: {name}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Create tag — ERROR: {e}")
        self._reload()

    def _on_delete_tag(self, name: str) -> None:
        # Look up which remotes have this tag (cache only — fast, no network).
        remotes_with_tag: list[str] = []
        if self._remote_tag_cache and self._repo_path:
            try:
                cache_data = self._remote_tag_cache.load(self._repo_path)
                for remote, names in cache_data.items():
                    if name in names:
                        remotes_with_tag.append(remote)
            except Exception as e:
                logger.warning(
                    "Remote tag cache load failed for %s: %s",
                    self._repo_path,
                    e,
                )

        if remotes_with_tag:
            remote_list = ", ".join(remotes_with_tag)
            box = QMessageBox(self)
            box.setWindowTitle("Delete Tag")
            box.setText(
                f"Tag '{name}' exists on {remote_list}.\n\nDelete locally and from {remote_list}?"
            )
            both_btn = box.addButton("Local + remote", QMessageBox.AcceptRole)
            local_btn = box.addButton("Local only", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            # The global QSS sets `QDialog QPushButton { min-width: 72px; }`
            # which clips longer labels. Override at the dialog level with the
            # same selector specificity.
            box.setStyleSheet("QDialog QPushButton { min-width: 160px; padding: 6px 20px; }")
            box.exec()
            clicked = box.clickedButton()
            if clicked is both_btn:
                self._delete_tag_local_and_remote(name, remotes_with_tag)
            elif clicked is local_btn:
                self._delete_tag_local_only(name)
            return

        # No remote has it — original simple flow.
        if QMessageBox.question(self, "Delete Tag", f"Delete tag '{name}'?") != QMessageBox.Yes:
            return
        self._delete_tag_local_only(name)

    def _delete_tag_local_only(self, name: str) -> None:
        try:
            self._commands.delete_tag.execute(name)
            self._log_panel.log(f"Deleted tag: {name}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Delete tag {name} — ERROR: {e}")
        self._reload()

    def _delete_tag_local_and_remote(self, name: str, remotes: list[str]) -> None:
        # Local delete first (synchronous), then each remote in background.
        try:
            self._commands.delete_tag.execute(name)
            self._log_panel.log(f"Deleted tag: {name}")
        except Exception as e:
            self._log_panel.expand()
            self._log_panel.log_error(f"Delete tag {name} — ERROR: {e}")
            self._reload()
            return

        for remote in remotes:

            def _fn(r=remote):
                self._commands.delete_remote_tag.execute(r, name)
                # Update cache: remove the tag from this remote's list.
                if self._remote_tag_cache and self._repo_path:
                    try:
                        data = self._remote_tag_cache.load(self._repo_path)
                        if r in data and name in data[r]:
                            data[r] = [t for t in data[r] if t != name]
                            self._remote_tag_cache.save(self._repo_path, data)
                    except Exception as e:
                        logger.warning(
                            "Remote tag cache update failed for %s (remote=%s, tag=%s): %s",
                            self._repo_path,
                            r,
                            name,
                            e,
                        )

            self._run_remote_op(f"Delete tag {name} from {remote}", _fn)
        self._reload()
