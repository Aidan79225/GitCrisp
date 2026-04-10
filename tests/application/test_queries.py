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
    reader.get_commits.assert_called_once_with(50, 0, extra_tips=None)
    assert len(result) == 1


def test_get_commit_graph_default_limit():
    reader = _reader()
    reader.get_commits.return_value = []
    GetCommitGraph(reader).execute()
    reader.get_commits.assert_called_once_with(200, 0, extra_tips=None)


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


from git_gui.application.queries import GetRepoState
from git_gui.domain.entities import RepoState, RepoStateInfo


class _FakeReader:
    def __init__(self, info):
        self._info = info
    def repo_state(self):
        return self._info


def test_get_repo_state_passthrough():
    info = RepoStateInfo(state=RepoState.MERGING, head_branch="main")
    q = GetRepoState(_FakeReader(info))
    assert q.execute() == info


from git_gui.application.queries import IsAncestor


class _FakeAncestorReader:
    def is_ancestor(self, a, d):
        return (a, d) == ("anc", "desc")


def test_is_ancestor_query_passthrough():
    q = IsAncestor(_FakeAncestorReader())
    assert q.execute("anc", "desc") is True
    assert q.execute("x", "y") is False


from git_gui.application.queries import GetMergeAnalysis
from git_gui.domain.entities import MergeAnalysisResult

class _FakeMergeAnalysisReader:
    def merge_analysis(self, oid):
        return MergeAnalysisResult(can_ff=True, is_up_to_date=False)

def test_get_merge_analysis_passthrough():
    q = GetMergeAnalysis(_FakeMergeAnalysisReader())
    result = q.execute("abc123")
    assert result.can_ff is True
    assert result.is_up_to_date is False


from git_gui.application.queries import GetMergeHead, GetMergeMsg, HasUnresolvedConflicts

class _FakeMergeHeadReader:
    def get_merge_head(self):
        return "abc123"

class _FakeMergeMsgReader:
    def get_merge_msg(self):
        return "Merge branch 'feature'"

class _FakeConflictReader:
    def __init__(self, val):
        self._val = val
    def has_unresolved_conflicts(self):
        return self._val

def test_get_merge_head_passthrough():
    assert GetMergeHead(_FakeMergeHeadReader()).execute() == "abc123"

def test_get_merge_msg_passthrough():
    assert GetMergeMsg(_FakeMergeMsgReader()).execute() == "Merge branch 'feature'"

def test_has_unresolved_conflicts_passthrough():
    assert HasUnresolvedConflicts(_FakeConflictReader(True)).execute() is True
    assert HasUnresolvedConflicts(_FakeConflictReader(False)).execute() is False
