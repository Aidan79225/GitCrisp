"""The commits an interactive rebase replays, as `get_commit_range` lists them.

The dialog's list replaces git's own todo, so it has to name exactly what
`git rebase -i <merge-base>` would replay: every non-merge commit reachable
from HEAD but not from the merge-base. A commit missing from the list is
dropped from the rebased branch; a merge in it stops the rebase.
"""

from __future__ import annotations

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository

SIG = pygit2.Signature("T", "t@example.com")


def _commit(repo: pygit2.Repository, message: str, parents: list[str]) -> str:
    builder = repo.TreeBuilder()
    builder.insert("f.txt", repo.create_blob(message.encode()), pygit2.GIT_FILEMODE_BLOB)
    return str(repo.create_commit(None, SIG, SIG, message, builder.write(), parents))


@pytest.fixture
def raw(repo_path) -> pygit2.Repository:
    return pygit2.Repository(str(repo_path))


def test_a_merge_base_reached_only_through_a_merge_still_bounds_the_range(raw, repo_path):
    """feature merged main after branching, so the merge-base is off its first-parent chain."""
    root = str(raw.head.target)
    b = _commit(raw, "B", [root])
    main_tip = _commit(raw, "C", [b])
    f1 = _commit(raw, "F1", [b])
    merge = _commit(raw, "merge main into feature", [f1, main_tip])
    f2 = _commit(raw, "F2", [merge])

    commits = Pygit2Repository(str(repo_path)).get_commit_range(f2, main_tip)

    assert [c.message for c in commits] == ["F1", "F2"]


def test_commits_a_merged_side_branch_brought_in_are_replayed_without_the_merge(raw, repo_path):
    root = str(raw.head.target)
    main_tip = _commit(raw, "C", [root])
    f1 = _commit(raw, "F1", [root])
    topic = _commit(raw, "T1", [root])
    merge = _commit(raw, "merge topic into feature", [f1, topic])
    f2 = _commit(raw, "F2", [merge])

    commits = Pygit2Repository(str(repo_path)).get_commit_range(f2, main_tip)

    assert sorted(c.message for c in commits) == ["F1", "F2", "T1"]
