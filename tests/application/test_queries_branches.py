from unittest.mock import MagicMock
from git_gui.domain.entities import LocalBranchInfo
from git_gui.application.queries import ListLocalBranchesWithUpstream


def test_list_local_branches_with_upstream_calls_reader():
    reader = MagicMock()
    reader.list_local_branches_with_upstream.return_value = [
        LocalBranchInfo("master", "origin/master", "abc", "msg"),
    ]
    q = ListLocalBranchesWithUpstream(reader)
    result = q.execute()
    assert result == [LocalBranchInfo("master", "origin/master", "abc", "msg")]
    reader.list_local_branches_with_upstream.assert_called_once()
