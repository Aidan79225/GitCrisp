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
        check=True,
        capture_output=True,
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
        check=True,
        capture_output=True,
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


def test_force_remove_overrides_a_lock(repo_with_worktree):
    """git needs --force twice to remove a locked worktree; a single one fails
    with the same "locked" error, so the UI's force prompt came back forever."""
    main, wt = repo_with_worktree
    subprocess.run(
        ["git", "-C", str(main), "worktree", "lock", "--reason", "busy", str(wt)],
        check=True,
        capture_output=True,
    )
    cli = WorktreeCli(str(main))
    cli.remove(str(wt), force=True)
    assert not wt.exists()


def test_a_dirty_worktree_under_a_non_ascii_folder_is_reported_dirty(repo_with_worktree, tmp_path):
    """git's message names the path in UTF-8; decoded in the locale code page
    (cp950, cp1252) the read failed, the message was lost, and the user got a
    bare exit status instead of the force prompt."""
    main, _ = repo_with_worktree
    wt = tmp_path / "Łódź 功能" / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-b", "other", str(wt)],
        cwd=main,
        check=True,
        capture_output=True,
    )
    (wt / "a.txt").write_text("changed\n")

    with pytest.raises(WorktreeDirtyError):
        WorktreeCli(str(main)).remove(str(wt), force=False)


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def worktree_with_submodule(repo_with_worktree, tmp_path, monkeypatch):
    """A clean linked worktree whose submodule has been initialised."""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    main, _ = repo_with_worktree
    child = tmp_path / "child"
    child.mkdir()
    _git(child, "init", "-q")
    _git(child, "config", "user.name", "T")
    _git(child, "config", "user.email", "t@e.com")
    _git(child, "commit", "-q", "--allow-empty", "-m", "c")
    _git(main, "submodule", "add", str(child), "sub")
    _git(main, "commit", "-q", "-m", "add sub")
    wt = tmp_path / "wt-sub"
    _git(main, "worktree", "add", "-b", "with-sub", str(wt))
    _git(wt, "submodule", "update", "--init")
    return main, wt


def test_a_worktree_with_submodules_can_be_force_removed(worktree_with_submodule):
    """git refuses "working trees containing submodules" without --force; that
    message matched neither pattern, so the force prompt never appeared."""
    main, wt = worktree_with_submodule
    cli = WorktreeCli(str(main))

    with pytest.raises(WorktreeDirtyError):
        cli.remove(str(wt), force=False)
    cli.remove(str(wt), force=True)

    assert not wt.exists()
