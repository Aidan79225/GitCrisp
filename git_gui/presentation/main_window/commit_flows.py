# git_gui/presentation/main_window/commit_flows.py
from __future__ import annotations

from PySide6.QtGui import QGuiApplication


class CommitFlowsMixin:
    """Commit-context UX flows (clipboard copy, etc.).

    Mixin — not instantiable on its own. Relies on composite-provided
    attributes set up by MainWindow's __init__ (`self._diff`,
    `self.statusBar()`).
    """

    def _wire_commit_flow_signals(self) -> None:
        self._diff.commit_oid_copy_requested.connect(self._on_commit_oid_copy_requested)
        self._diff.ref_copy_requested.connect(self._on_ref_copy_requested)

    def _on_commit_oid_copy_requested(self, oid: str) -> None:
        QGuiApplication.clipboard().setText(oid)
        self.statusBar().showMessage(f"Copied {oid[:7]}", 2000)

    def _on_ref_copy_requested(self, name: str) -> None:
        QGuiApplication.clipboard().setText(name)
        self.statusBar().showMessage(f"Copied {name}", 2000)
