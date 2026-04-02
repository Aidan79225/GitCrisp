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
    w.merge.assert_called_once_with("feature/x")


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
