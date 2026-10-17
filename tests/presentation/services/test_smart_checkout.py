from __future__ import annotations

from pathlib import Path

import pygit2
import pytest

from git_gui.application.commands import Checkout
from git_gui.application.queries import FindWorktreeForBranch
from git_gui.domain.entities import Worktree
from git_gui.infrastructure.pygit2 import Pygit2Repository
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


def _wt(path="/tmp/wt", branch="feat", is_main=False):
    return Worktree(
        path=path,
        branch=branch,
        head_sha="x",
        is_locked=False,
        lock_reason=None,
        is_bare=False,
        is_main=is_main,
    )


def _switches(sc: SmartCheckout) -> list[str]:
    received: list[str] = []
    sc.switch_to_worktree_requested.connect(received.append)
    return received


def test_normal_checkout_does_not_emit_switch(qtbot):
    checkout = _FakeCheckout()
    sc = SmartCheckout(checkout, _FakeFinder())  # type: ignore[arg-type]
    received = _switches(sc)
    sc.execute("feat")
    assert checkout.calls == ["feat"]
    assert received == []


def test_a_branch_held_by_another_worktree_switches_without_checking_out(qtbot):
    checkout = _FakeCheckout()
    sc = SmartCheckout(checkout, _FakeFinder(result=_wt("/tmp/wt", "feat")))  # type: ignore[arg-type]
    received = _switches(sc)
    sc.execute("feat")
    assert received == ["/tmp/wt"]
    assert checkout.calls == []


def test_a_branch_held_by_this_worktree_is_checked_out_here(qtbot, tmp_path):
    checkout = _FakeCheckout()
    here = _wt(str(tmp_path), "feat")
    sc = SmartCheckout(checkout, _FakeFinder(result=here), current_worktree=str(tmp_path))  # type: ignore[arg-type]
    received = _switches(sc)
    sc.execute("feat")
    assert checkout.calls == ["feat"]
    assert received == []


def test_a_checkout_error_propagates_when_no_worktree_holds_the_branch(qtbot):
    checkout = _FakeCheckout(raise_on=pygit2.GitError("some unrelated failure"))
    sc = SmartCheckout(checkout, _FakeFinder(result=None))  # type: ignore[arg-type]
    with pytest.raises(pygit2.GitError):
        sc.execute("feat")


# ── Against a real repository and a real linked worktree ─────────────────────


@pytest.fixture
def main_with_feat_worktree(tmp_path) -> tuple[Path, Path]:
    """`main` on master, with branch `feat` (which changes a.txt) checked out in `wt`."""
    main = tmp_path / "main"
    repo = pygit2.init_repository(str(main))
    sig = pygit2.Signature("T", "t@e.com")
    (main / "a.txt").write_text("master\n")
    repo.index.add("a.txt")
    repo.index.write()
    base = repo.create_commit("refs/heads/master", sig, sig, "init", repo.index.write_tree(), [])
    blob = repo.create_blob(b"feat\n")
    builder = repo.TreeBuilder(repo[base].tree)
    builder.insert("a.txt", blob, pygit2.enums.FileMode.BLOB)
    repo.create_commit("refs/heads/feat", sig, sig, "feat", builder.write(), [base])
    wt = tmp_path / "wt"
    repo.add_worktree("wt", str(wt), repo.branches.local["feat"])
    return main, wt


def _smart_checkout(session_path: Path) -> SmartCheckout:
    repo = Pygit2Repository(str(session_path))
    return SmartCheckout(
        Checkout(repo), FindWorktreeForBranch(repo), current_worktree=str(session_path)
    )


def test_checking_out_a_branch_held_by_a_linked_worktree_switches_to_it(
    qtbot, main_with_feat_worktree
):
    main, wt = main_with_feat_worktree
    sc = _smart_checkout(main)
    received = _switches(sc)

    sc.execute("feat")

    assert [Path(p) for p in received] == [wt.resolve()]
    assert (main / "a.txt").read_text() == "master\n"
    assert pygit2.Repository(str(main)).head.shorthand == "master"


def test_without_a_current_worktree_the_session_is_taken_for_the_main_one(
    qtbot, main_with_feat_worktree
):
    main, wt = main_with_feat_worktree
    repo = Pygit2Repository(str(main))
    sc = SmartCheckout(Checkout(repo), FindWorktreeForBranch(repo))
    received = _switches(sc)

    sc.execute("feat")

    assert [Path(p) for p in received] == [wt.resolve()]
    assert (main / "a.txt").read_text() == "master\n"


def test_checking_out_the_main_worktrees_branch_from_a_linked_one_switches_to_main(
    qtbot, main_with_feat_worktree
):
    main, wt = main_with_feat_worktree
    sc = _smart_checkout(wt)
    received = _switches(sc)

    sc.execute("master")

    assert [Path(p) for p in received] == [main.resolve()]
    assert pygit2.Repository(str(wt)).head.shorthand == "feat"
