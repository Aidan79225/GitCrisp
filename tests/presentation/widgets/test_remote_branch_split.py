from unittest.mock import MagicMock

from git_gui.domain.entities import Remote
from git_gui.presentation.widgets.remote_branch_split import listed_remotes, split_if_unambiguous


def test_a_listed_remote_whose_name_holds_a_slash_owns_the_branch():
    assert split_if_unambiguous("team/upstream/feature", ["team", "team/upstream"]) == (
        "team/upstream",
        "feature",
    )


def test_a_name_with_one_slash_splits_without_the_remotes():
    assert split_if_unambiguous("origin/feature", None) == ("origin", "feature")


def test_a_name_with_more_slashes_has_no_split_without_the_remotes():
    assert split_if_unambiguous("team/upstream/feature", None) is None


def test_remotes_that_cannot_be_listed_are_none_not_empty():
    # An empty list means "no remotes", under which every name splits at its first '/'.
    queries = MagicMock()
    queries.list_remotes.execute.side_effect = RuntimeError("'bad..name' is not valid")

    assert listed_remotes(queries) is None


def test_listed_remotes_are_their_names():
    queries = MagicMock()
    queries.list_remotes.execute.return_value = [Remote("origin", "u", "u")]

    assert listed_remotes(queries) == ["origin"]
