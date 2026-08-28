from pathlib import Path

import pygit2
import pytest

from git_gui.domain.entities import MergeStrategy, RepoState
from git_gui.infrastructure.pygit2 import Pygit2Repository


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
        (b.name for b in branches if not b.is_remote and b.name in ["main", "master"]), "master"
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
    main_name = (
        "main"
        if "main" in [br.name for br in impl.get_branches() if not br.is_remote]
        else "master"
    )
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


def test_checkout_after_aborted_merge_does_not_see_stale_conflicts(writable_repo):
    """Regression: merging via the long-lived impl populates its in-memory
    index with conflict entries. Aborting via subprocess clears the on-disk
    index but NOT the cached in-memory one. A subsequent checkout through the
    same impl must not fail with 'unresolved conflicts exist in the index'."""
    impl, path = writable_repo
    raw = pygit2.Repository(str(path))
    sig = pygit2.Signature("T", "t@t.com")
    base = raw.head.target

    # Advance master with a change to README.md
    (path / "README.md").write_text("master change\n")
    raw.index.add("README.md")
    raw.index.write()
    tree_a = raw.index.write_tree()
    raw.create_commit("refs/heads/master", sig, sig, "master change", tree_a, [base])

    # Conflicting branch from base
    raw.branches.local.create("conflict-branch", raw.get(base))
    raw.checkout("refs/heads/conflict-branch")
    (path / "README.md").write_text("branch change\n")
    raw.index.add("README.md")
    raw.index.write()
    tree_b = raw.index.write_tree()
    raw.create_commit("refs/heads/conflict-branch", sig, sig, "branch change", tree_b, [base])

    # Back to master, then merge THROUGH THE IMPL so its in-memory index is
    # polluted with conflict entries (this is the real app's code path).
    raw.checkout("refs/heads/master")
    raw.set_head("refs/heads/master")
    impl.merge("conflict-branch")
    assert impl.repo_state().state == RepoState.MERGING

    # Abort via subprocess — clears the on-disk index, not impl's cached one.
    impl.merge_abort()
    assert impl.repo_state().state == RepoState.CLEAN

    # Checkout through the same impl must succeed.
    impl.checkout("conflict-branch")
    assert pygit2.Repository(str(path)).head.shorthand == "conflict-branch"


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

    # Assert on libgit2's own view here rather than repo_state(); the
    # REBASING mapping is covered by test_repo_state_rebasing.
    raw2 = pygit2.Repository(str(path))
    assert raw2.state() != pygit2.enums.RepositoryState.NONE

    impl.rebase_abort()

    raw3 = pygit2.Repository(str(path))
    assert raw3.state() == pygit2.enums.RepositoryState.NONE


def test_rebase_continue_errors_on_clean_repo(writable_repo):
    impl, path = writable_repo
    with pytest.raises(RuntimeError):
        impl.rebase_continue()


# ---- interactive_rebase ----


def test_interactive_rebase_squash(repo_impl, repo_path):
    """Squash 3 commits into 2 by squashing the last into its predecessor."""
    # Create A → B → C chain
    (repo_path / "b.txt").write_text("b")
    repo_impl.stage(["b.txt"])
    commit_b = repo_impl.commit("commit B")

    (repo_path / "c.txt").write_text("c")
    repo_impl.stage(["c.txt"])
    commit_c = repo_impl.commit("commit C")

    # Get the initial commit oid (the base)
    commits = repo_impl.get_commits(limit=10)
    base_oid = commits[-1].oid  # the initial commit (oldest)

    # Squash C into B
    entries = [
        ("pick", commit_b.oid),
        ("squash", commit_c.oid),
    ]
    repo_impl.interactive_rebase(base_oid, entries)

    # After rebase: should have initial commit + one squashed commit = 2 total
    new_commits = repo_impl.get_commits(limit=10)
    assert len(new_commits) == 2
    # The squashed commit should contain both files
    import os

    assert os.path.exists(repo_path / "b.txt")
    assert os.path.exists(repo_path / "c.txt")


def test_interactive_rebase_drop(repo_impl, repo_path):
    """Drop the last commit."""
    (repo_path / "b.txt").write_text("b")
    repo_impl.stage(["b.txt"])
    commit_b = repo_impl.commit("commit B")

    (repo_path / "c.txt").write_text("c")
    repo_impl.stage(["c.txt"])
    commit_c = repo_impl.commit("commit C")

    commits = repo_impl.get_commits(limit=10)
    base_oid = commits[-1].oid

    entries = [
        ("pick", commit_b.oid),
        ("drop", commit_c.oid),
    ]
    repo_impl.interactive_rebase(base_oid, entries)

    new_commits = repo_impl.get_commits(limit=10)
    assert len(new_commits) == 2  # initial + B only
    import os

    assert os.path.exists(repo_path / "b.txt")
    assert not os.path.exists(repo_path / "c.txt")


# ── amend ────────────────────────────────────────────────────────────────────


def test_amend_replaces_head_and_keeps_parent(writable_repo):
    impl, path = writable_repo
    (path / "a.txt").write_text("v1\n")
    impl.stage(["a.txt"])
    original = impl.commit("typo in subjcet")
    raw = pygit2.Repository(str(path))
    original_parents = [str(p) for p in raw[raw.head.target].parent_ids]

    amended = impl.amend_commit("fix: typo in subject")

    assert amended.message == "fix: typo in subject"
    assert amended.oid != original.oid
    raw = pygit2.Repository(str(path))
    assert str(raw.head.target) == amended.oid
    # History is rewritten in place, not extended.
    assert [str(p) for p in raw[raw.head.target].parent_ids] == original_parents


def test_amend_folds_in_staged_changes(writable_repo):
    impl, path = writable_repo
    (path / "b.txt").write_text("first\n")
    impl.stage(["b.txt"])
    impl.commit("add b.txt")

    (path / "forgotten.txt").write_text("oops\n")
    impl.stage(["forgotten.txt"])
    amended = impl.amend_commit("add b.txt and forgotten.txt")

    raw = pygit2.Repository(str(path))
    tree = raw[raw.head.target].tree
    assert "b.txt" in tree and "forgotten.txt" in tree
    assert amended.message == "add b.txt and forgotten.txt"


def test_amend_preserves_original_author(writable_repo):
    """`git commit --amend` keeps the author and only moves the committer."""
    impl, path = writable_repo
    (path / "c.txt").write_text("x\n")
    impl.stage(["c.txt"])
    impl.commit("original")
    raw = pygit2.Repository(str(path))
    before = raw[raw.head.target].author

    impl.amend_commit("reworded")

    raw = pygit2.Repository(str(path))
    after = raw[raw.head.target].author
    assert (after.name, after.email, after.time) == (before.name, before.email, before.time)


def test_amend_on_unborn_branch_raises(tmp_path):
    from git_gui.infrastructure.pygit2 import Pygit2Repository

    pygit2.init_repository(str(tmp_path))
    impl = Pygit2Repository(str(tmp_path))
    with pytest.raises(ValueError, match="no commits yet"):
        impl.amend_commit("nothing to amend")


def test_rebase_onto_remote_tracking_branch(writable_repo):
    """`rebase` resolves remote-tracking branches, not just local ones.

    Regression: the lookup only consulted ``branches.local``, so rebasing
    onto ``origin/<name>`` raised ``KeyError: Branch not found``.
    """
    impl, path = writable_repo
    raw = pygit2.Repository(str(path))
    base = raw.head.target
    sig = pygit2.Signature("Test User", "test@example.com")

    # origin/staging: base -> S
    (path / "s.txt").write_text("s")
    raw.index.add("s.txt")
    raw.index.write()
    tree = raw.index.write_tree()
    staging_oid = raw.create_commit(None, sig, sig, "S on staging", tree, [base])
    raw.references.create("refs/remotes/origin/staging", staging_oid)
    raw.index.read_tree(raw.get(base).tree)
    raw.index.write()
    (path / "s.txt").unlink()

    # local branch adds M on top of base
    (path / "m.txt").write_text("m")
    impl.stage(["m.txt"])
    impl.commit("M on master")

    impl.rebase("origin/staging")

    assert impl.is_ancestor(str(staging_oid), impl.get_head_oid()) is True
