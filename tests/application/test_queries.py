from unittest.mock import MagicMock
from datetime import datetime
from git_gui.domain.entities import Commit, Branch, FileStatus, Hunk, Stash
from git_gui.domain.ports import IRepositoryReader
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetCommitFiles,
    GetFileDiff, GetWorkingTree, GetStashes,
)


def _make_commit(oid="abc"):
    return Commit(oid=oid, message="msg", author="A", timestamp=datetime.now(), parents=[])


def _reader():
    return MagicMock(spec=IRepositoryReader)


def test_get_commit_graph_delegates_to_reader():
    reader = _reader()
    reader.get_commits.return_value = [_make_commit()]
    result = GetCommitGraph(reader).execute(limit=50)
    reader.get_commits.assert_called_once_with(50, 0)
    assert len(result) == 1


def test_get_commit_graph_default_limit():
    reader = _reader()
    reader.get_commits.return_value = []
    GetCommitGraph(reader).execute()
    reader.get_commits.assert_called_once_with(200, 0)


def test_get_branches_delegates_to_reader():
    reader = _reader()
    reader.get_branches.return_value = [Branch("main", False, True, "abc")]
    result = GetBranches(reader).execute()
    reader.get_branches.assert_called_once()
    assert result[0].name == "main"


def test_get_commit_files_delegates_to_reader():
    reader = _reader()
    reader.get_commit_files.return_value = [FileStatus("a.py", "staged", "modified")]
    result = GetCommitFiles(reader).execute("abc")
    reader.get_commit_files.assert_called_once_with("abc")
    assert result[0].path == "a.py"


def test_get_file_diff_delegates_to_reader():
    reader = _reader()
    reader.get_file_diff.return_value = [Hunk("@@ -1,1 +1,2 @@", [("+", "line\n")])]
    result = GetFileDiff(reader).execute("abc", "a.py")
    reader.get_file_diff.assert_called_once_with("abc", "a.py")
    assert len(result) == 1


def test_get_working_tree_delegates_to_reader():
    reader = _reader()
    reader.get_working_tree.return_value = [FileStatus("b.py", "unstaged", "modified")]
    result = GetWorkingTree(reader).execute()
    reader.get_working_tree.assert_called_once()
    assert result[0].path == "b.py"


def test_get_stashes_delegates_to_reader():
    reader = _reader()
    reader.get_stashes.return_value = [Stash(0, "WIP", "stash_oid")]
    result = GetStashes(reader).execute()
    reader.get_stashes.assert_called_once()
    assert result[0].index == 0


def test_get_staged_diff_delegates_to_reader():
    reader = _reader()
    reader.get_staged_diff.return_value = [Hunk("@@ -1,1 +1,2 @@", [("+", "line\n")])]
    from git_gui.application.queries import GetStagedDiff
    result = GetStagedDiff(reader).execute("a.py")
    reader.get_staged_diff.assert_called_once_with("a.py")
    assert len(result) == 1
