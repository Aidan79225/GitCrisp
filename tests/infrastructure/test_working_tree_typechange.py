"""A type change (file <-> symlink) is a modification the user stages and
unstages like any other, not an unrecognised status."""

import pygit2

from git_gui.domain.entities import FileDelta, FileStatus, StagingState
from git_gui.infrastructure.pygit2 import Pygit2Repository
from git_gui.infrastructure.pygit2._helpers import _map_statuses


def test_a_staged_type_change_is_listed_as_staged(repo_path):
    impl = Pygit2Repository(str(repo_path))
    link_target = impl._repo.create_blob(b"README.target")
    impl._repo.index.add(pygit2.IndexEntry("README.md", link_target, pygit2.GIT_FILEMODE_LINK))
    impl._repo.index.write()

    files = impl.get_working_tree()

    assert FileStatus("README.md", StagingState.STAGED, FileDelta.MODIFIED) in files


def test_an_unstaged_type_change_is_an_unstaged_modification():
    assert _map_statuses(pygit2.GIT_STATUS_WT_TYPECHANGE) == [
        (StagingState.UNSTAGED, FileDelta.MODIFIED)
    ]
