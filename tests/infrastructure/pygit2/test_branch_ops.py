"""BranchOps mixin — resilience against dangling/unresolvable refs."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


@pytest.fixture
def repo_with_dangling_remote_ref(tmp_path):
    """Repo whose packed-refs enumerate a remote ref that fails to resolve.

    Mirrors a real-world directory/file (D/F) conflict: both
    ``refs/remotes/origin/beta`` and ``refs/remotes/origin/beta/2.68.0`` are
    packed, so libgit2 *lists* the names but ``branches.remote[name]`` raises
    ``KeyError``. This reproduced the bug where a single bad ref aborted
    ``get_branches()``, killing the graph + sidebar worker and leaving the
    repo rendering empty.
    """
    p = tmp_path / "main"
    p.mkdir()
    repo = pygit2.init_repository(str(p))
    repo.config["user.name"] = "T"
    repo.config["user.email"] = "t@e.com"
    sig = pygit2.Signature("T", "t@e.com")
    (p / "a.txt").write_text("hi\n")
    repo.index.add("a.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    oid = repo.create_commit("refs/heads/master", sig, sig, "init", tree, [])
    (Path(repo.path) / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted \n"
        f"{oid} refs/remotes/origin/beta\n"
        f"{oid} refs/remotes/origin/beta/2.68.0\n"
    )
    return p


def test_get_branches_skips_unresolvable_remote_refs(repo_with_dangling_remote_ref):
    impl = Pygit2Repository(str(repo_with_dangling_remote_ref))

    # Must not raise despite the dangling packed remote refs.
    branches = impl.get_branches()

    names = {b.name for b in branches}
    # The resolvable local branch is still returned — the bad remote refs are
    # skipped rather than aborting the whole enumeration.
    assert "master" in names


# ── checkout of a branch held by another worktree ───────────────────────────


def _git(cwd, *args) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo_with_feat_in_a_linked_worktree(tmp_path):
    """Main worktree on a clean ``master``; ``feat`` is checked out in a
    linked worktree and differs from master in a.txt and only_feat.txt."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "master")
    _git(main, "config", "user.email", "t@t")
    _git(main, "config", "user.name", "t")
    (main / "a.txt").write_text("master\n")
    _git(main, "add", ".")
    _git(main, "commit", "-q", "-m", "init")
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "feat", str(wt))
    (wt / "a.txt").write_text("feat\n")
    (wt / "only_feat.txt").write_text("feat\n")
    _git(wt, "add", ".")
    _git(wt, "commit", "-q", "-m", "feat work")
    return main


def test_checkout_of_a_branch_held_by_another_worktree_leaves_the_tree_alone(
    repo_with_feat_in_a_linked_worktree,
):
    main = repo_with_feat_in_a_linked_worktree
    impl = Pygit2Repository(str(main))

    with pytest.raises(RuntimeError, match="already used by worktree at"):
        impl.checkout("feat")

    assert _git(main, "status", "--porcelain") == ""
    assert (main / "a.txt").read_text() == "master\n"
    assert _git(main, "symbolic-ref", "HEAD").strip() == "refs/heads/master"


def test_checkout_of_the_current_branch_still_succeeds(repo_with_feat_in_a_linked_worktree):
    impl = Pygit2Repository(str(repo_with_feat_in_a_linked_worktree))

    impl.checkout("master")

    assert impl.repo_state().head_branch == "master"
