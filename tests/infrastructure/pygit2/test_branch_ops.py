"""BranchOps mixin — resilience against dangling/unresolvable refs."""

from __future__ import annotations

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
