from unittest.mock import MagicMock
from datetime import datetime
from git_gui.domain.entities import Branch, Commit
from git_gui.domain.ports import IRepositoryWriter
from git_gui.application.commands import (
    StageFiles, UnstageFiles, CreateCommit,
    Checkout, CreateBranch, DeleteBranch,
    Merge, Rebase, Push, Pull, Fetch, Stash, PopStash,
)


def _writer():
    return MagicMock(spec=IRepositoryWriter)


def _make_commit():
    return Commit(oid="abc", message="msg", author="A", timestamp=datetime.now(), parents=[])


def test_stage_files():
    w = _writer()
    StageFiles(w).execute(["a.py", "b.py"])
    w.stage.assert_called_once_with(["a.py", "b.py"])


def test_unstage_files():
    w = _writer()
    UnstageFiles(w).execute(["a.py"])
    w.unstage.assert_called_once_with(["a.py"])


def test_create_commit():
    w = _writer()
    w.commit.return_value = _make_commit()
    result = CreateCommit(w).execute("feat: add thing")
    w.commit.assert_called_once_with("feat: add thing")
    assert result.oid == "abc"


def test_checkout():
    w = _writer()
    Checkout(w).execute("feature/x")
    w.checkout.assert_called_once_with("feature/x")


def test_create_branch():
    w = _writer()
    w.create_branch.return_value = Branch("new", False, False, "abc")
    result = CreateBranch(w).execute("new", "abc")
    w.create_branch.assert_called_once_with("new", "abc")
    assert result.name == "new"


def test_delete_branch():
    w = _writer()
    DeleteBranch(w).execute("old")
    w.delete_branch.assert_called_once_with("old")


def test_merge():
    w = _writer()
    Merge(w).execute("feature/x")
    from git_gui.domain.entities import MergeStrategy
    w.merge.assert_called_once_with("feature/x", MergeStrategy.ALLOW_FF, None)


def test_rebase():
    w = _writer()
    Rebase(w).execute("main")
    w.rebase.assert_called_once_with("main")


def test_push():
    w = _writer()
    Push(w).execute("origin", "main")
    w.push.assert_called_once_with("origin", "main")


def test_pull():
    w = _writer()
    Pull(w).execute("origin", "main")
    w.pull.assert_called_once_with("origin", "main")


def test_fetch():
    w = _writer()
    Fetch(w).execute("origin")
    w.fetch.assert_called_once_with("origin")


def test_stash():
    w = _writer()
    Stash(w).execute("WIP: save")
    w.stash.assert_called_once_with("WIP: save")


def test_pop_stash():
    w = _writer()
    PopStash(w).execute(0)
    w.pop_stash.assert_called_once_with(0)


from git_gui.application.commands import MergeCommit, RebaseOntoCommit


class _FakeMergeCommitWriter:
    def __init__(self):
        self.merge_commit_called = None
        self.rebase_onto_commit_called = None
    def merge_commit(self, oid, strategy=None, message=None):
        self.merge_commit_called = oid
    def rebase_onto_commit(self, oid):
        self.rebase_onto_commit_called = oid


def test_merge_commit_passes_oid():
    w = _FakeMergeCommitWriter()
    MergeCommit(w).execute("abcdef1234")
    assert w.merge_commit_called == "abcdef1234"


def test_rebase_onto_commit_passes_oid():
    w = _FakeMergeCommitWriter()
    RebaseOntoCommit(w).execute("abcdef1234")
    assert w.rebase_onto_commit_called == "abcdef1234"


from git_gui.domain.entities import MergeStrategy

class _FakeStrategyWriter:
    def __init__(self):
        self.merge_args = None
        self.merge_commit_args = None
    def merge(self, branch, strategy=None, message=None):
        self.merge_args = (branch, strategy, message)
    def merge_commit(self, oid, strategy=None, message=None):
        self.merge_commit_args = (oid, strategy, message)

def test_merge_passes_strategy_and_message():
    w = _FakeStrategyWriter()
    Merge(w).execute("feature", strategy=MergeStrategy.NO_FF, message="custom")
    assert w.merge_args == ("feature", MergeStrategy.NO_FF, "custom")

def test_merge_commit_passes_strategy_and_message():
    w = _FakeStrategyWriter()
    MergeCommit(w).execute("abc123", strategy=MergeStrategy.FF_ONLY, message=None)
    assert w.merge_commit_args == ("abc123", MergeStrategy.FF_ONLY, None)


from git_gui.application.commands import MergeAbort, RebaseAbort, RebaseContinue

class _FakeAbortWriter:
    def __init__(self):
        self.merge_abort_called = False
        self.rebase_abort_called = False
        self.rebase_continue_called = False
    def merge_abort(self):
        self.merge_abort_called = True
    def rebase_abort(self):
        self.rebase_abort_called = True
    def rebase_continue(self):
        self.rebase_continue_called = True

def test_merge_abort_delegates():
    w = _FakeAbortWriter()
    MergeAbort(w).execute()
    assert w.merge_abort_called

def test_rebase_abort_delegates():
    w = _FakeAbortWriter()
    RebaseAbort(w).execute()
    assert w.rebase_abort_called

def test_rebase_continue_delegates():
    w = _FakeAbortWriter()
    RebaseContinue(w).execute()
    assert w.rebase_continue_called
