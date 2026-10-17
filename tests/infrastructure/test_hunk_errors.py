"""A hunk that cannot be staged, unstaged or discarded raises an error that
says why, so the user is not left believing the click worked."""

from pathlib import Path

import pytest

from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.infrastructure.pygit2 import Pygit2Repository


def _edited_repo(repo_path: Path) -> Pygit2Repository:
    impl = Pygit2Repository(str(repo_path))
    (repo_path / "f.txt").write_text("one\ntwo\nthree\n")
    impl.stage(["f.txt"])
    impl.commit("seed f.txt")
    (repo_path / "f.txt").write_text("one\nTWO\nthree\n")
    return impl


def _only_unstaged_header(impl: Pygit2Repository) -> str:
    [hunk] = impl.get_file_diff(WORKING_TREE_OID, "f.txt")
    return hunk.header


def test_a_hunk_stage_refused_by_git_carries_gits_reason(repo_path):
    impl = _edited_repo(repo_path)
    header = _only_unstaged_header(impl)
    (repo_path / ".git" / "index.lock").write_text("")

    with pytest.raises(RuntimeError, match="index.lock"):
        impl.stage_hunk("f.txt", header)


def test_a_hunk_unstage_refused_by_git_carries_gits_reason(repo_path):
    impl = _edited_repo(repo_path)
    impl.stage(["f.txt"])
    [hunk] = impl.get_staged_diff("f.txt")
    (repo_path / ".git" / "index.lock").write_text("")

    with pytest.raises(RuntimeError, match="index.lock"):
        impl.unstage_hunk("f.txt", hunk.header)


@pytest.mark.parametrize("operation", ["stage_hunk", "unstage_hunk", "discard_hunk"])
def test_a_hunk_that_is_no_longer_in_the_diff_is_reported(repo_path, operation):
    impl = _edited_repo(repo_path)

    with pytest.raises(RuntimeError, match="not found in f.txt"):
        getattr(impl, operation)("f.txt", "@@ -7,3 +7,3 @@\n")
