"""A commit that turns a file into a symlink changed one file, and its diff
shows both what the file held and where the link now points."""

from pathlib import Path

import pygit2

from git_gui.domain.entities import FileDelta, FileStatus, LineKind, StagingState
from git_gui.infrastructure.pygit2 import Pygit2Repository


def _commit_file_turned_into_symlink(repo_path: Path) -> tuple[Pygit2Repository, str]:
    """README.md, a regular file in HEAD, becomes a link to docs/README.md.

    Built from trees so the test runs where symlinks cannot be created.
    """
    impl = Pygit2Repository(str(repo_path))
    repo = impl._repo
    link = repo.create_blob(b"docs/README.md")
    builder = repo.TreeBuilder(repo.head.peel(pygit2.Commit).tree)
    builder.insert("README.md", link, pygit2.GIT_FILEMODE_LINK)
    sig = repo.default_signature
    oid = repo.create_commit("HEAD", sig, sig, "link README", builder.write(), [repo.head.target])
    return impl, str(oid)


def test_a_type_change_lists_the_file_once_as_modified(repo_path):
    impl, oid = _commit_file_turned_into_symlink(repo_path)

    files = impl.get_commit_files(oid)

    assert files == [FileStatus("README.md", StagingState.STAGED, FileDelta.MODIFIED)]


def test_a_type_change_diff_shows_the_old_content_and_the_link_target(repo_path):
    impl, oid = _commit_file_turned_into_symlink(repo_path)

    lines = [line for hunk in impl.get_commit_diff_map(oid)["README.md"] for line in hunk.lines]

    assert (LineKind.REMOVED, "# Test Repo\n") in lines
    assert (LineKind.ADDED, "docs/README.md") in lines
