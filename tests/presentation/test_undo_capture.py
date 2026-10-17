"""Each history-rewriting operation offers an Undo back to where HEAD was before it.

The flows read HEAD themselves. Reading it after the operation instead would
make the Undo link reset to the state the user is already in.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

import pytest
from PySide6.QtWidgets import QDialog

from git_gui.domain.entities import (
    Branch,
    MergeAnalysisResult,
    MergeStrategy,
    RepoState,
    RepoStateInfo,
    ResetMode,
)
from git_gui.presentation.main_window import merge_rebase_flows, reset_flow
from git_gui.presentation.main_window.cherry_pick_revert_flows import CherryPickRevertFlowsMixin
from git_gui.presentation.main_window.merge_rebase_flows import MergeRebaseFlowsMixin
from git_gui.presentation.main_window.reflog_flow import ReflogFlowMixin
from git_gui.presentation.main_window.reset_flow import ResetFlowMixin

HEAD_BEFORE = "b" * 40
HEAD_AFTER = "a" * 40
TARGET = "c" * 40

_OPERATION_COMMANDS = (
    "cherry_pick",
    "revert_commit",
    "reset_branch",
    "merge",
    "merge_commit",
    "rebase",
    "rebase_onto_commit",
)


class _Host(CherryPickRevertFlowsMixin, MergeRebaseFlowsMixin, ResetFlowMixin, ReflogFlowMixin):
    def __init__(self) -> None:
        self._queries = MagicMock()
        self._commands = MagicMock()
        self._log_panel = MagicMock()
        self._undoable: dict[str, str] = {}

    def _reload(self) -> None:
        pass


class _AcceptingDialog:
    """Stands in for the merge and reset dialogs: the user confirms."""

    Accepted = QDialog.Accepted

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def exec(self):
        return QDialog.Accepted

    def result_value(self):
        return SimpleNamespace(strategy=MergeStrategy.NO_FF, message="Merge")

    def result_mode(self):
        return ResetMode.MIXED


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setattr(merge_rebase_flows, "MergeDialog", _AcceptingDialog)
    monkeypatch.setattr(reset_flow, "ResetDialog", _AcceptingDialog)

    h = _Host()
    _make_operations_move_head(h)
    queries = h._queries
    queries.get_identity.execute.return_value = ("T", "t@e.com")
    queries.get_branches.execute.return_value = [Branch("feature", False, False, TARGET)]
    queries.get_merge_analysis.execute.return_value = MergeAnalysisResult(
        can_ff=False, is_up_to_date=False
    )
    queries.get_repo_state.execute.return_value = RepoStateInfo(RepoState.CLEAN, "main")
    queries.get_commit_detail.execute.return_value = SimpleNamespace(message="subject\n")
    queries.get_working_tree.execute.return_value = []
    return h


def _make_operations_move_head(host: _Host) -> None:
    head = {"oid": HEAD_BEFORE}

    def move_head(*_args, **_kwargs) -> None:
        head["oid"] = HEAD_AFTER

    host._queries.get_head_oid.execute.side_effect = lambda: head["oid"]
    for name in _OPERATION_COMMANDS:
        getattr(host._commands, name).execute.side_effect = move_head


OPERATIONS = {
    "cherry-pick": lambda h: h._on_cherry_pick(TARGET),
    "revert": lambda h: h._on_revert(TARGET),
    "reset to commit": lambda h: h._on_reset_to_commit(TARGET, ResetMode.MIXED),
    "merge branch": lambda h: h._on_merge("feature"),
    "merge commit": lambda h: h._on_merge_commit(TARGET),
    "rebase onto branch": lambda h: h._on_rebase("feature"),
    "rebase onto commit": lambda h: h._on_rebase_onto_commit(TARGET),
}


@pytest.mark.parametrize("run_operation", OPERATIONS.values(), ids=OPERATIONS.keys())
def test_the_undo_link_returns_to_where_head_was_before_the_operation(host, run_operation):
    run_operation(host)

    host._log_panel.log_action.assert_called_once_with(ANY, "Undo", HEAD_BEFORE)
