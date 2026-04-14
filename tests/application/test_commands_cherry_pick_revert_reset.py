from unittest.mock import MagicMock

from git_gui.domain.entities import ResetMode
from git_gui.domain.ports import IRepositoryWriter
from git_gui.application.commands import (
    CherryPickCommit, RevertCommit, ResetBranch,
    CherryPickAbort, CherryPickContinue,
    RevertAbort, RevertContinue,
)


def _writer():
    return MagicMock(spec=IRepositoryWriter)


def test_cherry_pick_commit_delegates():
    w = _writer()
    CherryPickCommit(w).execute("abc123")
    w.cherry_pick.assert_called_once_with("abc123")


def test_revert_commit_delegates():
    w = _writer()
    RevertCommit(w).execute("def456")
    w.revert_commit.assert_called_once_with("def456")


def test_reset_branch_delegates_with_mode():
    w = _writer()
    ResetBranch(w).execute("abc123", ResetMode.HARD)
    w.reset_to.assert_called_once_with("abc123", ResetMode.HARD)


def test_reset_branch_mixed_mode():
    w = _writer()
    ResetBranch(w).execute("abc123", ResetMode.MIXED)
    w.reset_to.assert_called_once_with("abc123", ResetMode.MIXED)


def test_cherry_pick_abort_delegates():
    w = _writer()
    CherryPickAbort(w).execute()
    w.cherry_pick_abort.assert_called_once_with()


def test_cherry_pick_continue_delegates():
    w = _writer()
    CherryPickContinue(w).execute()
    w.cherry_pick_continue.assert_called_once_with()


def test_revert_abort_delegates():
    w = _writer()
    RevertAbort(w).execute()
    w.revert_abort.assert_called_once_with()


def test_revert_continue_delegates():
    w = _writer()
    RevertContinue(w).execute()
    w.revert_continue.assert_called_once_with()
