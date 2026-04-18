import pygit2
import pytest
from pathlib import Path
from git_gui.infrastructure.pygit2 import Pygit2Repository


@pytest.fixture
def multi_hunk_repo(repo_path) -> tuple[Pygit2Repository, Path]:
    """Create a repo with a file that has two separate unstaged hunks."""
    impl = Pygit2Repository(str(repo_path))
    # Write a file with several lines, commit it
    lines = [f"line {i}\n" for i in range(1, 21)]
    (repo_path / "multi.txt").write_text("".join(lines))
    impl.stage(["multi.txt"])
    impl.commit("add multi.txt")

    # Modify two separate regions to create two hunks
    lines[1] = "CHANGED line 2\n"    # near top
    lines[17] = "CHANGED line 18\n"  # near bottom
    (repo_path / "multi.txt").write_text("".join(lines))
    return impl, repo_path


def test_stage_hunk_stages_only_one_hunk(multi_hunk_repo):
    impl, path = multi_hunk_repo
    # Get the unstaged diff — should have 2 hunks
    hunks = impl.get_file_diff("WORKING_TREE", "multi.txt")
    assert len(hunks) == 2

    # Stage only the first hunk
    impl.stage_hunk("multi.txt", hunks[0].header)

    # Now staged diff should have 1 hunk (the one we staged)
    staged = impl.get_staged_diff("multi.txt")
    assert len(staged) == 1
    assert "CHANGED line 2" in "".join(c for _, c in staged[0].lines)

    # Unstaged diff should still have 1 hunk (the one we didn't stage)
    remaining = impl.get_file_diff("WORKING_TREE", "multi.txt")
    assert len(remaining) == 1
    assert "CHANGED line 18" in "".join(c for _, c in remaining[0].lines)


def test_unstage_hunk_unstages_only_one_hunk(multi_hunk_repo):
    impl, path = multi_hunk_repo
    # Stage the whole file first
    impl.stage(["multi.txt"])

    # Staged diff should have 2 hunks
    staged = impl.get_staged_diff("multi.txt")
    assert len(staged) == 2

    # Unstage only the first hunk
    impl.unstage_hunk("multi.txt", staged[0].header)

    # Staged should now have 1 hunk
    staged_after = impl.get_staged_diff("multi.txt")
    assert len(staged_after) == 1
    assert "CHANGED line 18" in "".join(c for _, c in staged_after[0].lines)

    # Unstaged should have 1 hunk (the one we unstaged)
    unstaged = impl.get_file_diff("WORKING_TREE", "multi.txt")
    assert len(unstaged) == 1
    assert "CHANGED line 2" in "".join(c for _, c in unstaged[0].lines)
