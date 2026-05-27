"""Tests for the git-worktree-remove subprocess wrapper.

Uses real pygit2 fixtures (no subprocess mocking). Builds a small repo with
a real worktree, then exercises the wrapper's remove paths.
"""
from __future__ import annotations

import subprocess

import pygit2
import pytest

from git_gui.infrastructure.worktree_cli import (
    WorktreeCli,
    WorktreeCommandError,
    WorktreeDirtyError,
    WorktreeLockedError,
)


@pytest.fixture
def repo_with_worktree(tmp_path):
    """Create a main repo + a sibling worktree on a feature branch."""
    main = tmp_path / "main"
    repo = pygit2.init_repository(str(main))
    repo.config["user.name"] = "T"
    repo.config["user.email"] = "t@e.com"
    sig = pygit2.Signature("T", "t@e.com")
    (main / "a.txt").write_text("hello\n")
    repo.index.add("a.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("refs/heads/master", sig, sig, "init", tree, [])
    # Make a feature branch
    head_oid = repo.head.target
    repo.references.create("refs/heads/feat", head_oid)
    # Use subprocess to create the worktree
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", str(wt_path), "feat"],
        check=True, capture_output=True,
    )
    return main, wt_path


def test_remove_clean_worktree_succeeds(repo_with_worktree):
    main, wt = repo_with_worktree
    cli = WorktreeCli(str(main))
    cli.remove(str(wt), force=False)
    assert not wt.exists()


def test_remove_dirty_worktree_without_force_raises_dirty(repo_with_worktree):
    main, wt = repo_with_worktree
    (wt / "a.txt").write_text("changed\n")
    cli = WorktreeCli(str(main))
    with pytest.raises(WorktreeDirtyError):
        cli.remove(str(wt), force=False)
    assert wt.exists()


def test_remove_dirty_worktree_with_force_succeeds(repo_with_worktree):
    main, wt = repo_with_worktree
    (wt / "a.txt").write_text("changed\n")
    cli = WorktreeCli(str(main))
    cli.remove(str(wt), force=True)
    assert not wt.exists()


def test_remove_locked_worktree_without_force_raises_locked(repo_with_worktree):
    main, wt = repo_with_worktree
    subprocess.run(
        ["git", "-C", str(main), "worktree", "lock", str(wt)],
        check=True, capture_output=True,
    )
    cli = WorktreeCli(str(main))
    with pytest.raises(WorktreeLockedError):
        cli.remove(str(wt), force=False)
    assert wt.exists()


def test_remove_unknown_path_raises_generic(repo_with_worktree, tmp_path):
    main, _ = repo_with_worktree
    cli = WorktreeCli(str(main))
    bogus = tmp_path / "does-not-exist"
    with pytest.raises(WorktreeCommandError):
        cli.remove(str(bogus), force=False)
