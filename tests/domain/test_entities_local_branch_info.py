from git_gui.domain.entities import LocalBranchInfo, TrackedBranch


def test_local_branch_info_fields():
    b = LocalBranchInfo(
        name="master",
        upstream="origin/master",
        last_commit_sha="a1b2c3d",
        last_commit_message="fix: x",
    )
    assert b.name == "master"
    assert b.upstream == "origin/master"
    assert b.last_commit_sha == "a1b2c3d"
    assert b.last_commit_message == "fix: x"


def test_local_branch_info_upstream_optional():
    b = LocalBranchInfo(name="wip", upstream=None, last_commit_sha="abc", last_commit_message="WIP")
    assert b.upstream is None
    assert b.tracks is None


def test_a_branch_tracked_on_this_repo_is_local():
    assert TrackedBranch(".", "refs/heads/origin/main").is_local
    assert not TrackedBranch("origin", "refs/heads/main").is_local


def test_a_tracked_branch_is_named_without_refs_heads():
    assert TrackedBranch("origin", "refs/heads/feature/x").branch == "feature/x"
    assert TrackedBranch("origin", "refs/pull/1/head").branch == "refs/pull/1/head"
