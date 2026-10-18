"""Discarding a conflicted file the current branch deleted resolves the conflict
as that deletion."""

import subprocess
from pathlib import Path

from git_gui.infrastructure.pygit2 import Pygit2Repository


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _merge_a_modification_into_a_deletion(repo_path: Path) -> None:
    """Leaves f.txt as `DU`: deleted on master, modified on the merged branch."""
    (repo_path / "f.txt").write_text("base\n")
    _git(repo_path, "add", "f.txt")
    _git(repo_path, "commit", "-qm", "base")
    _git(repo_path, "checkout", "-qb", "other")
    (repo_path / "f.txt").write_text("theirs\n")
    _git(repo_path, "commit", "-qam", "modify f")
    _git(repo_path, "checkout", "-q", "master")
    _git(repo_path, "rm", "-q", "f.txt")
    _git(repo_path, "commit", "-qm", "delete f")
    subprocess.run(["git", "merge", "other"], cwd=repo_path, capture_output=True)


def test_discarding_a_file_deleted_by_us_resolves_its_conflict(repo_path):
    _merge_a_modification_into_a_deletion(repo_path)
    impl = Pygit2Repository(str(repo_path))
    assert impl.has_unresolved_conflicts()

    impl.discard_file("f.txt")

    assert not impl.has_unresolved_conflicts()
    assert not (repo_path / "f.txt").exists()
