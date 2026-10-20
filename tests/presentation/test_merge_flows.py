"""Merging a branch or a commit into HEAD from the context menus."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from git_gui.domain.entities import Branch, MergeStrategy
from git_gui.presentation.dialogs.merge_dialog import MergeRequest
from git_gui.presentation.main_window.merge_rebase_flows import MergeRebaseFlowsMixin

MODULE = "git_gui.presentation.main_window.merge_rebase_flows"
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


def _accept_merge(host, start_merge, *, identity_set: bool) -> None:
    host._queries.get_branches.execute.return_value = [Branch("feature", False, False, OID)]
    with (
        patch(f"{MODULE}.MergeDialog") as dialog_cls,
        patch(f"{MODULE}.ensure_identity", return_value=identity_set),
    ):
        dialog = dialog_cls.return_value
        dialog.exec.return_value = dialog_cls.Accepted
        dialog.result_value.return_value = MergeRequest(MergeStrategy.NO_FF, "Merge")
        start_merge()


@pytest.mark.parametrize(
    ("start", "command"),
    [
        (lambda h: h._on_merge("feature"), "merge"),
        (lambda h: h._on_merge_commit(OID), "merge_commit"),
    ],
    ids=["branch", "commit"],
)
def test_a_merge_waits_for_a_git_identity(host, start, command):
    """Without one the merge writes MERGE_HEAD and the merged index, then
    fails to sign the commit, leaving the repo half merged."""
    _accept_merge(host, lambda: start(host), identity_set=False)
    getattr(host._commands, command).execute.assert_not_called()

    _accept_merge(host, lambda: start(host), identity_set=True)
    getattr(host._commands, command).execute.assert_called_once()
