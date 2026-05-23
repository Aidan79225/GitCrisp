from __future__ import annotations

import pytest
import pygit2

from git_gui.domain.entities import Worktree
from git_gui.presentation.services.smart_checkout import SmartCheckout


class _FakeCheckout:
    def __init__(self, raise_on=None):
        self._raise = raise_on
        self.calls: list[str] = []
    def execute(self, branch):
        self.calls.append(branch)
        if self._raise is not None:
            raise self._raise


class _FakeFinder:
    def __init__(self, result=None):
        self._result = result
        self.calls: list[str] = []
    def execute(self, branch):
        self.calls.append(branch)
        return self._result


def _wt(path="/tmp/wt", branch="feat"):
    return Worktree(
        path=path, branch=branch, head_sha="x",
        is_locked=False, lock_reason=None, is_bare=False, is_main=False,
    )


def test_normal_checkout_does_not_emit_switch(qtbot):
    checkout = _FakeCheckout()
    finder = _FakeFinder()
    sc = SmartCheckout(checkout, finder)  # type: ignore[arg-type]
    received = []
    sc.switch_to_worktree_requested.connect(received.append)
    sc.execute("feat")
    assert checkout.calls == ["feat"]
    assert received == []


def test_worktree_collision_switches_and_does_not_raise(qtbot):
    err = pygit2.GitError(
        "branch 'feat' already used by worktree at /tmp/wt"
    )
    checkout = _FakeCheckout(raise_on=err)
    finder = _FakeFinder(result=_wt("/tmp/wt", "feat"))
    sc = SmartCheckout(checkout, finder)  # type: ignore[arg-type]
    received: list[str] = []
    sc.switch_to_worktree_requested.connect(received.append)
    sc.execute("feat")  # must NOT raise
    assert received == ["/tmp/wt"]


def test_worktree_collision_no_owning_worktree_reraises(qtbot):
    err = pygit2.GitError(
        "branch 'feat' already used by worktree at /missing"
    )
    checkout = _FakeCheckout(raise_on=err)
    finder = _FakeFinder(result=None)
    sc = SmartCheckout(checkout, finder)  # type: ignore[arg-type]
    with pytest.raises(pygit2.GitError):
        sc.execute("feat")


def test_unrelated_error_propagates(qtbot):
    err = pygit2.GitError("some unrelated failure")
    checkout = _FakeCheckout(raise_on=err)
    finder = _FakeFinder(result=_wt())
    sc = SmartCheckout(checkout, finder)  # type: ignore[arg-type]
    with pytest.raises(pygit2.GitError):
        sc.execute("feat")
    assert finder.calls == []  # collision detection rejected; finder not called
