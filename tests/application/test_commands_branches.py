from unittest.mock import MagicMock
from git_gui.application.commands import (
    SetBranchUpstream, UnsetBranchUpstream, RenameBranch, ResetBranchToRef,
)


def test_set_branch_upstream():
    w = MagicMock()
    SetBranchUpstream(w).execute("feature", "origin/feature")
    w.set_branch_upstream.assert_called_once_with("feature", "origin/feature")


def test_unset_branch_upstream():
    w = MagicMock()
    UnsetBranchUpstream(w).execute("feature")
    w.unset_branch_upstream.assert_called_once_with("feature")


def test_rename_branch():
    w = MagicMock()
    RenameBranch(w).execute("old", "new")
    w.rename_branch.assert_called_once_with("old", "new")


def test_reset_branch_to_ref():
    w = MagicMock()
    ResetBranchToRef(w).execute("feature", "origin/feature")
    w.reset_branch_to_ref.assert_called_once_with("feature", "origin/feature")
