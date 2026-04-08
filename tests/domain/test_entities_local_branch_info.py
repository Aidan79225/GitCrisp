from git_gui.domain.entities import LocalBranchInfo


def test_local_branch_info_fields():
    b = LocalBranchInfo(
        name="master", upstream="origin/master",
        last_commit_sha="a1b2c3d", last_commit_message="fix: x",
    )
    assert b.name == "master"
    assert b.upstream == "origin/master"
    assert b.last_commit_sha == "a1b2c3d"
    assert b.last_commit_message == "fix: x"


def test_local_branch_info_upstream_optional():
    b = LocalBranchInfo(name="wip", upstream=None,
                        last_commit_sha="abc", last_commit_message="WIP")
    assert b.upstream is None
