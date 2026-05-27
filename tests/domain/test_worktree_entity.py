from __future__ import annotations

import dataclasses

import pytest

from git_gui.domain.entities import Worktree


def test_worktree_construction():
    wt = Worktree(
        path="/tmp/repo-feat-x",
        branch="feat/x",
        head_sha="abc1234",
        is_locked=False,
        lock_reason=None,
        is_bare=False,
        is_main=False,
    )
    assert wt.path == "/tmp/repo-feat-x"
    assert wt.branch == "feat/x"
    assert wt.head_sha == "abc1234"
    assert wt.is_locked is False
    assert wt.lock_reason is None
    assert wt.is_bare is False
    assert wt.is_main is False


def test_worktree_supports_detached_head():
    wt = Worktree(
        path="/tmp/repo-detached",
        branch=None,
        head_sha="deadbeef",
        is_locked=False,
        lock_reason=None,
        is_bare=False,
        is_main=False,
    )
    assert wt.branch is None


def test_worktree_supports_locked_with_reason():
    wt = Worktree(
        path="/tmp/repo-locked",
        branch="hotfix",
        head_sha="abc",
        is_locked=True,
        lock_reason="rebuilding artifacts overnight",
        is_bare=False,
        is_main=False,
    )
    assert wt.is_locked is True
    assert wt.lock_reason == "rebuilding artifacts overnight"


def test_worktree_is_frozen():
    wt = Worktree(
        path="/tmp/r", branch="main", head_sha="abc",
        is_locked=False, lock_reason=None, is_bare=False, is_main=True,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        wt.branch = "other"  # type: ignore[misc]
