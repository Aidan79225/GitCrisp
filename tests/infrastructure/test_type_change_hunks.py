"""A type change (file <-> symlink) reaches the working-tree views as both of
its sides, and either side moves the whole file in or out of the index:
git apply cannot express half of a type change."""

import os
from pathlib import Path

import pygit2
import pytest

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


@pytest.mark.parametrize("side", [0, 1])
def test_unstaging_either_side_of_a_type_change_restores_heads_entry(repo_path, side):
    impl = _stage_symlink_over_readme(repo_path)
    staged = impl.get_working_tree_diff_map()["README.md"][StagingState.STAGED]

    impl.unstage_hunk("README.md", staged[side].header)

    head_entry = impl._repo.head.peel(pygit2.Commit).tree["README.md"]
    entry = impl._repo.index["README.md"]
    assert (entry.id, entry.mode) == (head_entry.id, head_entry.filemode)


@pytest.mark.parametrize("side", [0, 1])
def test_staging_either_side_of_a_type_change_stages_the_link(repo_path, side):
    impl = Pygit2Repository(str(repo_path))
    (repo_path / "README.md").unlink()
    try:
        os.symlink("docs/README.md", repo_path / "README.md")
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot create symlinks")
    unstaged = impl.get_working_tree_diff_map()["README.md"][StagingState.UNSTAGED]

    impl.stage_hunk("README.md", unstaged[side].header)

    assert impl._repo.index["README.md"].mode == pygit2.GIT_FILEMODE_LINK
