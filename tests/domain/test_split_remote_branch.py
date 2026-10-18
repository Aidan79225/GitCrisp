from git_gui.domain.entities import split_remote_branch


def test_the_remote_ends_at_the_first_slash():
    assert split_remote_branch("origin/feature/x") == ("origin", "feature/x")


def test_a_name_without_a_slash_has_no_remote():
    assert split_remote_branch("feature") == ("", "feature")


def test_the_remote_is_the_part_before_the_first_slash():
    assert split_remote_branch("origin/feature/x", ["origin"]) == ("origin", "feature/x")


def test_a_remote_named_with_a_slash_owns_its_branches():
    assert split_remote_branch("gh/fork/topic", ["gh", "gh/fork"]) == ("gh/fork", "topic")


def test_a_shorter_remote_keeps_the_branches_the_longer_one_does_not_own():
    assert split_remote_branch("gh/fix/x", ["gh", "gh/fork"]) == ("gh", "fix/x")


def test_a_name_no_known_remote_owns_splits_at_the_first_slash():
    assert split_remote_branch("gone/feature/x", ["origin"]) == ("gone", "feature/x")


def test_a_name_missing_its_remote_or_branch_leaves_that_part_empty():
    assert split_remote_branch("/main", []) == ("", "main")
    assert split_remote_branch("origin/", ["origin"]) == ("origin", "")
