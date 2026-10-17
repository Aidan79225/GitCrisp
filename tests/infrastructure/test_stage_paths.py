"""Whole-file stage of paths that are neither plain edits nor plain deletions."""

import os
import subprocess
from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


def _symlink_or_skip(target: str, link: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot create symlinks")


def _assert_index_holds_link(impl: Pygit2Repository, path: str, target: bytes) -> None:
    impl._repo.index.read()
    entry = impl._repo.index[path]
    assert entry.mode == pygit2.GIT_FILEMODE_LINK
    assert impl._repo[entry.id].data == target


def test_staging_a_symlink_retargeted_to_a_missing_file_stages_the_new_target(repo_path):
    impl = Pygit2Repository(str(repo_path))
    (repo_path / "a.txt").write_text("a\n")
    link = repo_path / "link"
    _symlink_or_skip("a.txt", link)
    impl.stage(["a.txt", "link"])
    impl.commit("seed link")
    link.unlink()
    os.symlink("missing.txt", link)

    impl.stage(["link"])

    _assert_index_holds_link(impl, "link", b"missing.txt")


def test_staging_a_new_dangling_symlink_adds_it(repo_path):
    impl = Pygit2Repository(str(repo_path))
    _symlink_or_skip("nowhere.txt", repo_path / "newlink")

    impl.stage(["newlink"])

    _assert_index_holds_link(impl, "newlink", b"nowhere.txt")


def test_discarding_a_new_dangling_symlink_removes_it(repo_path):
    impl = Pygit2Repository(str(repo_path))
    link = repo_path / "newlink"
    _symlink_or_skip("nowhere.txt", link)

    impl.discard_file("newlink")

    assert not os.path.lexists(link)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_staging_a_deleted_file_resolves_its_modify_delete_conflict(repo_path):
    (repo_path / "f.txt").write_text("base\n")
    _git(repo_path, "add", "f.txt")
    _git(repo_path, "commit", "-qm", "base")
    _git(repo_path, "checkout", "-qb", "other")
    _git(repo_path, "rm", "-q", "f.txt")
    _git(repo_path, "commit", "-qm", "delete f")
    _git(repo_path, "checkout", "-q", "master")
    (repo_path / "f.txt").write_text("ours\n")
    _git(repo_path, "commit", "-qam", "modify f")
    subprocess.run(["git", "merge", "other"], cwd=repo_path, capture_output=True)
    impl = Pygit2Repository(str(repo_path))
    assert impl.has_unresolved_conflicts()
    (repo_path / "f.txt").unlink()

    impl.stage(["f.txt"])

    assert not impl.has_unresolved_conflicts()
    assert "f.txt" not in impl._repo.index
