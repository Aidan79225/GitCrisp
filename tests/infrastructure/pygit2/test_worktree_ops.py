"""WorktreeOps mixin — exercised via Pygit2Repository against real repos."""
from __future__ import annotations
from pathlib import Path
import subprocess

import pytest
import pygit2

from git_gui.infrastructure.pygit2 import Pygit2Repository
from git_gui.infrastructure.worktree_cli import WorktreeDirtyError


@pytest.fixture
def fresh_repo(tmp_path):
    """Empty-ish repo with one commit on master."""
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
    repo.create_commit("refs/heads/master", sig, sig, "init", tree, [])
    return p


def test_list_worktrees_returns_just_main_when_no_extra(fresh_repo):
    impl = Pygit2Repository(str(fresh_repo))
    wts = impl.list_worktrees()
    assert len(wts) == 1
    main = wts[0]
    assert main.is_main is True
    assert Path(main.path) == Path(str(fresh_repo)).resolve()
    assert main.branch == "master"
    assert main.is_locked is False


def test_list_worktrees_includes_added_worktree(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True, capture_output=True,
    )
    impl = Pygit2Repository(str(fresh_repo))
    wts = impl.list_worktrees()
    branches = {wt.branch for wt in wts}
    assert "master" in branches
    assert "feat" in branches
    feat = next(wt for wt in wts if wt.branch == "feat")
    assert feat.is_main is False
    assert Path(feat.path) == wt_path.resolve()


def test_add_worktree_creates_new_branch_and_directory(fresh_repo, tmp_path):
    impl = Pygit2Repository(str(fresh_repo))
    target = tmp_path / "wt-new"
    wt = impl.add_worktree(
        str(target), "feat/new", create_branch=True, base_ref="master",
    )
    assert target.exists()
    assert wt.branch == "feat/new"
    assert wt.is_main is False
    repo = pygit2.Repository(str(fresh_repo))
    assert "refs/heads/feat/new" in [b for b in repo.references]


def test_add_worktree_attaches_existing_branch(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/existing", repo.head.target)
    impl = Pygit2Repository(str(fresh_repo))
    target = tmp_path / "wt-existing"
    wt = impl.add_worktree(
        str(target), "existing", create_branch=False, base_ref=None,
    )
    assert wt.branch == "existing"


def test_find_worktree_for_branch_returns_match(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add",
         str(tmp_path / "wt-feat"), "feat"],
        check=True, capture_output=True,
    )
    impl = Pygit2Repository(str(fresh_repo))
    wt = impl.find_worktree_for_branch("feat")
    assert wt is not None
    assert wt.branch == "feat"


def test_find_worktree_for_branch_returns_none_when_missing(fresh_repo):
    impl = Pygit2Repository(str(fresh_repo))
    assert impl.find_worktree_for_branch("does-not-exist") is None


def test_lock_and_unlock_round_trip(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True, capture_output=True,
    )
    impl = Pygit2Repository(str(fresh_repo))
    impl.lock_worktree(str(wt_path), reason="testing")
    wts = impl.list_worktrees()
    feat = next(wt for wt in wts if wt.branch == "feat")
    assert feat.is_locked is True

    impl.unlock_worktree(str(wt_path))
    wts = impl.list_worktrees()
    feat = next(wt for wt in wts if wt.branch == "feat")
    assert feat.is_locked is False


def test_remove_worktree_clean(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True, capture_output=True,
    )
    impl = Pygit2Repository(str(fresh_repo))
    impl.remove_worktree(str(wt_path), force=False)
    assert not wt_path.exists()


def test_remove_worktree_dirty_without_force_raises(fresh_repo, tmp_path):
    repo = pygit2.Repository(str(fresh_repo))
    repo.references.create("refs/heads/feat", repo.head.target)
    wt_path = tmp_path / "wt-feat"
    subprocess.run(
        ["git", "-C", str(fresh_repo), "worktree", "add", str(wt_path), "feat"],
        check=True, capture_output=True,
    )
    (wt_path / "a.txt").write_text("changed\n")
    impl = Pygit2Repository(str(fresh_repo))
    with pytest.raises(WorktreeDirtyError):
        impl.remove_worktree(str(wt_path), force=False)
