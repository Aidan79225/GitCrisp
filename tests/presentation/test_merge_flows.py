"""Merging a branch or a commit into HEAD from the context menus."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from git_gui.presentation.main_window.merge_rebase_flows import MergeRebaseFlowsMixin

OID = "a" * 40


class _Host(MergeRebaseFlowsMixin):
    """Bare composite standing in for MainWindow's attributes."""

    def __init__(self) -> None:
        self._queries = MagicMock()
        self._commands = MagicMock()
        self._log_panel = MagicMock()
        self.reloaded = 0

    def _reload(self) -> None:
        self.reloaded += 1

    def head_before_operation(self) -> str:
        return "h" * 40

    def _log_undoable(self, message: str, head_before: str | None) -> None:
        self._log_panel.log(message)


@pytest.fixture
def host():
    h = _Host()
    h._queries.get_merge_analysis.execute.return_value = MagicMock(is_up_to_date=False)
    h._queries.get_repo_state.execute.return_value = MagicMock(head_branch="master")
    return h


def test_a_failed_merge_analysis_is_logged_not_raised(host):
    host._queries.get_merge_analysis.execute.side_effect = RuntimeError("object not found")
    host._on_merge_commit(OID)
    host._log_panel.log_error.assert_called_once_with(
        "Merge commit aaaaaaa — ERROR: object not found"
    )
    assert host.reloaded == 1
