"""Structural tests for the git_gui.infrastructure.pygit2 subpackage.

Locks in the mixin-composite layout so future drift is caught:
- Pygit2Repository is importable from the package root.
- Its MRO includes every declared mixin.
- No non-dunder attribute is defined directly on the composite class —
  every public method must come from a mixin.
"""
from __future__ import annotations


def test_pygit2_repository_is_importable_from_package_root():
    from git_gui.infrastructure.pygit2 import Pygit2Repository
    assert Pygit2Repository is not None


def test_pygit2_repository_mro_includes_all_mixins():
    from git_gui.infrastructure.pygit2 import Pygit2Repository
    from git_gui.infrastructure.pygit2.branch_ops import BranchOps
    from git_gui.infrastructure.pygit2.commit_ops import CommitOps
    from git_gui.infrastructure.pygit2.diff_ops import DiffOps
    from git_gui.infrastructure.pygit2.merge_rebase_ops import MergeRebaseOps
    from git_gui.infrastructure.pygit2.remote_ops import RemoteOps
    from git_gui.infrastructure.pygit2.repo_state_ops import RepoStateOps
    from git_gui.infrastructure.pygit2.stage_ops import StageOps
    from git_gui.infrastructure.pygit2.stash_ops import StashOps
    from git_gui.infrastructure.pygit2.submodule_ops import SubmoduleOps
    from git_gui.infrastructure.pygit2.tag_ops import TagOps

    mro = Pygit2Repository.__mro__
    expected = {
        BranchOps, CommitOps, DiffOps, MergeRebaseOps, RemoteOps,
        RepoStateOps, StageOps, StashOps, SubmoduleOps, TagOps,
    }
    missing = expected - set(mro)
    assert not missing, f"Pygit2Repository MRO missing mixins: {missing}"


def test_pygit2_repository_composite_defines_no_own_public_attrs():
    """The composite must define only dunders (__init__, __module__, etc.)
    directly. All public behavior comes from mixins. This locks in the
    split pattern — adding a method on the composite would violate it."""
    from git_gui.infrastructure.pygit2 import Pygit2Repository

    own_non_dunders = [
        name for name in vars(Pygit2Repository) if not name.startswith("__")
    ]
    assert own_non_dunders == [], (
        f"Pygit2Repository should not define methods directly; "
        f"move them to the appropriate mixin. Found: {own_non_dunders}"
    )
