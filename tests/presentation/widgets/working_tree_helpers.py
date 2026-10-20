"""The real WorkingTreeWidget on mock buses, for tests that drive one path."""

from __future__ import annotations

from unittest.mock import MagicMock

from git_gui.presentation.widgets.working_tree import WorkingTreeWidget


def working_tree_widget(qtbot, repo_path: str | None = None) -> WorkingTreeWidget:
    """A committer identity is configured, so ``_on_commit`` gets past its
    check; a test of the missing-identity path overrides it."""
    queries = MagicMock()
    queries.get_identity.execute.return_value = ("Alice", "alice@example.com")
    widget = WorkingTreeWidget(queries, MagicMock(), repo_path)
    qtbot.addWidget(widget)
    return widget
