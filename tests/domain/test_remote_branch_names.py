"""Which remote a remote-tracking branch such as 'origin/feature/x' lives on."""

from __future__ import annotations

from git_gui.domain.entities import split_remote_branch


def test_a_remote_branch_splits_into_its_remote_and_branch():
    assert split_remote_branch("origin/main", ["origin"]) == ("origin", "main")


def test_a_slash_in_the_branch_name_stays_in_the_branch():
    assert split_remote_branch("origin/feature/foo", ["origin"]) == ("origin", "feature/foo")


def test_the_longest_remote_wins_when_remote_names_contain_a_slash():
    assert split_remote_branch("team/upstream/feature", ["team", "team/upstream"]) == (
        "team/upstream",
        "feature",
    )


def test_a_name_under_no_known_remote_splits_at_its_first_slash():
    assert split_remote_branch("gone/feature/foo", ["origin"]) == ("gone", "feature/foo")


def test_a_name_without_a_remote_part_has_no_split():
    assert split_remote_branch("no-slash", ["origin"]) is None
    assert split_remote_branch("/main", []) is None
    assert split_remote_branch("origin/", ["origin"]) is None
