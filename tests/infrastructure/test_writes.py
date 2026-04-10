import pygit2
import pytest
from pathlib import Path
from git_gui.infrastructure.pygit2_repo import Pygit2Repository
from git_gui.domain.entities import MergeStrategy, RepoState


@pytest.fixture
def writable_repo(repo_path) -> tuple[Pygit2Repository, Path]:
    return Pygit2Repository(str(repo_path)), repo_path


def test_stage_adds_new_file(writable_repo):
    impl, path = writable_repo
    (path / "new.txt").write_text("hello\n")
    impl.stage(["new.txt"])
    raw = pygit2.Repository(str(path))
    assert raw.status_file("new.txt") == pygit2.GIT_STATUS_INDEX_NEW


def test_unstage_removes_file_from_index(writable_repo):
    impl, path = writable_repo
    (path / "staged.txt").write_text("data\n")
    impl.stage(["staged.txt"])
    impl.unstage(["staged.txt"])
    raw = pygit2.Repository(str(path))
    assert raw.status_file("staged.txt") & pygit2.GIT_STATUS_WT_NEW


def test_commit_creates_new_commit(writable_repo):
    impl, path = writable_repo
    (path / "c.txt").write_text("content\n")
    impl.stage(["c.txt"])
    commit = impl.commit("feat: add c.txt")
    assert commit.message == "feat: add c.txt"
    raw = pygit2.Repository(str(path))
    assert str(raw.head.target) == commit.oid


def test_create_branch(writable_repo):
    impl, path = writable_repo
    commits = impl.get_commits(limit=1)
    branch = impl.create_branch("feature/x", commits[0].oid)
    assert branch.name == "feature/x"
    raw = pygit2.Repository(str(path))
    assert raw.branches.local["feature/x"] is not None


def test_checkout_switches_branch(writable_repo):
    impl, path = writable_repo
    commits = impl.get_commits(limit=1)
    impl.create_branch("feature/y", commits[0].oid)
    impl.checkout("feature/y")
    raw = pygit2.Repository(str(path))
    assert raw.head.shorthand == "feature/y"


def test_delete_branch(writable_repo):
    impl, path = writable_repo
    commits = impl.get_commits(limit=1)
    impl.create_branch("to-delete", commits[0].oid)
    impl.delete_branch("to-delete")
    raw = pygit2.Repository(str(path))
    assert "to-delete" not in list(raw.branches.local)


def test_stash_and_pop(writable_repo):
    impl, path = writable_repo
    (path / "README.md").write_text("modified\n")
    impl.stash("WIP: test stash")
    stashes = impl.get_stashes()
    assert len(stashes) == 1
    assert "WIP: test stash" in stashes[0].message
    impl.pop_stash(0)
    stashes_after = impl.get_stashes()
    assert len(stashes_after) == 0


def test_create_tag_lightweight(writable_repo):
    impl, path = writable_repo
    commits = impl.get_commits(limit=1)
    impl.create_tag("v1.0.0", commits[0].oid)
    raw = pygit2.Repository(str(path))
    assert "refs/tags/v1.0.0" in list(raw.references)


def test_create_tag_annotated(writable_repo):
    impl, path = writable_repo
    commits = impl.get_commits(limit=1)
    impl.create_tag("v2.0.0", commits[0].oid, message="Release 2.0")
    raw = pygit2.Repository(str(path))
    ref = raw.references["refs/tags/v2.0.0"]
    tag_obj = raw.get(ref.target)
    assert isinstance(tag_obj, pygit2.Tag)
    assert tag_obj.message == "Release 2.0"


def test_delete_tag(writable_repo):
    impl, path = writable_repo
    commits = impl.get_commits(limit=1)
    impl.create_tag("to-delete", commits[0].oid)
    impl.delete_tag("to-delete")
    raw = pygit2.Repository(str(path))
    assert "refs/tags/to-delete" not in list(raw.references)


def test_merge_commit_fast_forward(writable_repo):
    impl, path = writable_repo
    # Get the current HEAD oid
    head_oid = impl.get_head_oid()
    # Create a feature branch at HEAD
    impl.create_branch("feature", head_oid)
    # Checkout feature branch
    impl.checkout("feature")
    # Add a file on feature branch
    (path / "f.txt").write_text("f")
    impl.stage(["f.txt"])
    new_commit = impl.commit("on feature")
    # Get main/master branch name dynamically
    branches = impl.get_branches()
    main_branch_name = next(
        (b.name for b in branches if not b.is_remote and b.name in ["main", "master"]),
        "master"
    )
    # Checkout main/master branch
    impl.checkout(main_branch_name)

    # Merge the new commit
    impl.merge_commit(new_commit.oid)

    # Assert HEAD oid now equals the new commit oid (fast-forward)
    assert impl.get_head_oid() == new_commit.oid


def test_rebase_onto_commit(writable_repo):
    impl, path = writable_repo
    # main: A -> B; feature branches off A and adds C; rebase main onto C
    head_oid = impl.get_head_oid()  # A
    impl.create_branch("feature", head_oid)
    # main adds B
    (path / "b.txt").write_text("b")
    impl.stage(["b.txt"])
    b = impl.commit("B on main")
    # feature adds C
    impl.checkout("feature")
    (path / "c.txt").write_text("c")
    impl.stage(["c.txt"])
    c = impl.commit("C on feature")
    # back to main, rebase onto commit C
    main_name = "main" if "main" in [br.name for br in impl.get_branches() if not br.is_remote] else "master"
    impl.checkout(main_name)

    impl.rebase_onto_commit(c.oid)

    new_head = impl.get_head_oid()
    assert impl.is_ancestor(c.oid, new_head) is True


def test_merge_no_ff_creates_merge_commit_when_ff_possible(writable_repo):
    """NO_FF forces merge commit even on linear history."""
    impl, path = writable_repo
    head_oid = impl.get_head_oid()
    impl.create_branch("feature-noff", head_oid)
    impl.checkout("feature-noff")
    (path / "noff.txt").write_text("noff")
    impl.stage(["noff.txt"])
    impl.commit("feature work")
    branches = impl.get_branches()
    main_name = next(b.name for b in branches if not b.is_remote and b.name != "feature-noff")
    impl.checkout(main_name)
    impl.merge("feature-noff", strategy=MergeStrategy.NO_FF, message="Custom merge msg")
    new_head = impl.get_commit(impl.get_head_oid())
    assert len(new_head.parents) == 2
    assert "Custom merge msg" in new_head.message


def test_merge_ff_only_raises_when_not_possible(writable_repo):
    """FF_ONLY on diverged history raises."""
    impl, path = writable_repo
    head_oid = impl.get_head_oid()
    impl.create_branch("diverge", head_oid)
    (path / "m.txt").write_text("m")
    impl.stage(["m.txt"])
    impl.commit("main side")
    impl.checkout("diverge")
    (path / "d.txt").write_text("d")
    impl.stage(["d.txt"])
    impl.commit("diverge side")
    branches = impl.get_branches()
    main_name = next(b.name for b in branches if not b.is_remote and b.name != "diverge")
    impl.checkout(main_name)
    with pytest.raises(RuntimeError, match="[Cc]annot fast-forward"):
        impl.merge("diverge", strategy=MergeStrategy.FF_ONLY)


def test_merge_allow_ff_fast_forwards_when_possible(writable_repo):
    """ALLOW_FF on linear history fast-forwards (no merge commit)."""
    impl, path = writable_repo
    head_oid = impl.get_head_oid()
    impl.create_branch("feature-af", head_oid)
    impl.checkout("feature-af")
    (path / "af.txt").write_text("af")
    impl.stage(["af.txt"])
    feat_commit = impl.commit("feature work")
    branches = impl.get_branches()
    main_name = next(b.name for b in branches if not b.is_remote and b.name != "feature-af")
    impl.checkout(main_name)
    impl.merge("feature-af", strategy=MergeStrategy.ALLOW_FF)
    assert impl.get_head_oid() == feat_commit.oid
    new_head = impl.get_commit(impl.get_head_oid())
    assert len(new_head.parents) == 1


# ---- merge_abort / rebase_abort / rebase_continue ----


def _create_merge_conflict(impl, repo_path):
    """Helper: create divergent branches with conflicting changes, trigger merge conflict."""
    raw = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    base = raw.head.target

    # Commit on master
    (repo_path / "README.md").write_text("master change\n")
    raw.index.add("README.md")
    raw.index.write()
    tree_a = raw.index.write_tree()
    raw.create_commit("refs/heads/master", sig, sig, "master change", tree_a, [base])

    # Create branch from base with conflicting change
    raw.branches.local.create("conflict-branch", raw.get(base))
    raw.checkout("refs/heads/conflict-branch")
    (repo_path / "README.md").write_text("branch change\n")
    raw.index.add("README.md")
    raw.index.write()
    tree_b = raw.index.write_tree()
    raw.create_commit("refs/heads/conflict-branch", sig, sig, "branch change", tree_b, [base])

    # Switch back to master and merge -> conflict
    raw.checkout("refs/heads/master")
    raw.merge(raw.branches.local["conflict-branch"].target)


def test_merge_abort_restores_clean_state(writable_repo):
    impl, path = writable_repo
    _create_merge_conflict(impl, path)
    # Verify we are in MERGING state
    info = impl.repo_state()
    assert info.state == RepoState.MERGING

    impl.merge_abort()

    info = impl.repo_state()
    assert info.state == RepoState.CLEAN
    assert impl.get_merge_head() is None


def test_rebase_abort_restores_clean_state(writable_repo):
    impl, path = writable_repo
    raw = pygit2.Repository(str(path))
    sig = pygit2.Signature("T", "t@t.com")
    base = raw.head.target

    # Commit on master
    (path / "README.md").write_text("master rebase change\n")
    raw.index.add("README.md")
    raw.index.write()
    tree_a = raw.index.write_tree()
    raw.create_commit("refs/heads/master", sig, sig, "master rebase", tree_a, [base])

    # Create branch from base with conflicting change
    raw.branches.local.create("rebase-branch", raw.get(base))
    raw.checkout("refs/heads/rebase-branch")
    (path / "README.md").write_text("rebase branch change\n")
    raw.index.add("README.md")
    raw.index.write()
    tree_b = raw.index.write_tree()
    raw.create_commit("refs/heads/rebase-branch", sig, sig, "rebase branch", tree_b, [base])

    # Trigger rebase conflict via git rebase master
    with pytest.raises(RuntimeError):
        impl.rebase("master")

    # During rebase, git detaches HEAD so repo_state returns DETACHED_HEAD;
    # verify rebase is in progress via the rebase-merge directory
    import os
    raw2 = pygit2.Repository(str(path))
    assert raw2.state() != pygit2.GIT_REPOSITORY_STATE_NONE

    impl.rebase_abort()

    raw3 = pygit2.Repository(str(path))
    assert raw3.state() == pygit2.GIT_REPOSITORY_STATE_NONE


def test_rebase_continue_errors_on_clean_repo(writable_repo):
    impl, path = writable_repo
    with pytest.raises(RuntimeError):
        impl.rebase_continue()
