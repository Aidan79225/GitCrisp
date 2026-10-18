"""A type change (file <-> symlink) reaches the working-tree views as both of
its sides."""

from pathlib import Path

import pygit2

from git_gui.domain.entities import Hunk, LineKind, StagingState
from git_gui.infrastructure.pygit2 import Pygit2Repository


def _stage_symlink_over_readme(repo_path: Path) -> Pygit2Repository:
    """README.md is a regular file in HEAD and a link in the index.

    Built from an index entry so the test runs where symlinks cannot be created.
    """
    impl = Pygit2Repository(str(repo_path))
    link_target = impl._repo.create_blob(b"README.target")
    impl._repo.index.add(pygit2.IndexEntry("README.md", link_target, pygit2.GIT_FILEMODE_LINK))
    impl._repo.index.write()
    return impl


def _lines(hunks: list[Hunk]) -> list[tuple[LineKind, str]]:
    return [line for hunk in hunks for line in hunk.lines]


def test_the_all_files_view_shows_both_sides_of_a_staged_type_change(repo_path):
    impl = _stage_symlink_over_readme(repo_path)

    lines = _lines(impl.get_working_tree_diff_map()["README.md"][StagingState.STAGED])

    assert (LineKind.REMOVED, "# Test Repo\n") in lines
    assert (LineKind.ADDED, "README.target") in lines


def test_the_single_file_view_shows_both_sides_of_a_staged_type_change(repo_path):
    impl = _stage_symlink_over_readme(repo_path)

    lines = _lines(impl.get_staged_diff("README.md"))

    assert (LineKind.REMOVED, "# Test Repo\n") in lines
    assert (LineKind.ADDED, "README.target") in lines
