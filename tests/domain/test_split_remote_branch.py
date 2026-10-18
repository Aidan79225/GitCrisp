from git_gui.domain.entities import split_remote_branch


def test_the_remote_ends_at_the_first_slash():
    assert split_remote_branch("origin/feature/x") == ("origin", "feature/x")


def test_a_name_without_a_slash_has_no_remote():
    assert split_remote_branch("feature") == ("", "feature")
