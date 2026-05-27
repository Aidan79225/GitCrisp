"""Application use cases for worktrees — thin delegation to ports."""
from __future__ import annotations

from git_gui.application.commands import (
    AddWorktree,
    LockWorktree,
    RemoveWorktree,
    UnlockWorktree,
)
from git_gui.application.queries import FindWorktreeForBranch, ListWorktrees
from git_gui.domain.entities import Worktree


class _FakeReader:
    def __init__(self):
        self.list_calls = 0
        self.find_calls: list[str] = []
        self._wts: list[Worktree] = []
        self._find_result: Worktree | None = None

    def list_worktrees(self):
        self.list_calls += 1
        return list(self._wts)

    def find_worktree_for_branch(self, branch):
        self.find_calls.append(branch)
        return self._find_result


class _FakeWriter:
    def __init__(self):
        self.add_calls: list[tuple] = []
        self.remove_calls: list[tuple] = []
        self.lock_calls: list[tuple] = []
        self.unlock_calls: list[str] = []

    def add_worktree(self, path, branch, *, create_branch, base_ref):
        self.add_calls.append((path, branch, create_branch, base_ref))
        return Worktree(
            path=path, branch=branch, head_sha="x",
            is_locked=False, lock_reason=None, is_bare=False, is_main=False,
        )

    def remove_worktree(self, path, *, force):
        self.remove_calls.append((path, force))

    def lock_worktree(self, path, *, reason=None):
        self.lock_calls.append((path, reason))

    def unlock_worktree(self, path):
        self.unlock_calls.append(path)


def test_list_worktrees_delegates():
    reader = _FakeReader()
    q = ListWorktrees(reader)  # type: ignore[arg-type]
    q.execute()
    assert reader.list_calls == 1


def test_find_worktree_for_branch_delegates():
    reader = _FakeReader()
    q = FindWorktreeForBranch(reader)  # type: ignore[arg-type]
    q.execute("feat/x")
    assert reader.find_calls == ["feat/x"]


def test_add_worktree_delegates():
    writer = _FakeWriter()
    c = AddWorktree(writer)  # type: ignore[arg-type]
    c.execute("/tmp/x", "feat", create_branch=True, base_ref="master")
    assert writer.add_calls == [("/tmp/x", "feat", True, "master")]


def test_remove_worktree_delegates():
    writer = _FakeWriter()
    c = RemoveWorktree(writer)  # type: ignore[arg-type]
    c.execute("/tmp/x", force=True)
    assert writer.remove_calls == [("/tmp/x", True)]


def test_lock_worktree_delegates():
    writer = _FakeWriter()
    c = LockWorktree(writer)  # type: ignore[arg-type]
    c.execute("/tmp/x", reason="busy")
    assert writer.lock_calls == [("/tmp/x", "busy")]


def test_unlock_worktree_delegates():
    writer = _FakeWriter()
    c = UnlockWorktree(writer)  # type: ignore[arg-type]
    c.execute("/tmp/x")
    assert writer.unlock_calls == ["/tmp/x"]
