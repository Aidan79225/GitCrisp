"""The shared ``repo_path`` fixture must not depend on the developer's git config.

The suite deliberately leaves HOME alone (see ``_isolated_gitcrisp_home``), so
libgit2 reads the contributor's own global config. With
``init.defaultBranch=main`` there, a repo initialised without an explicit
branch points HEAD at an unborn ``main`` while the fixture commits to
``master``, and most of the infrastructure tests fail for that contributor
alone.
"""

from __future__ import annotations

import pygit2


def test_repo_path_commit_is_on_head_whatever_the_default_branch(
    global_default_branch_main, request
):
    path = request.getfixturevalue("repo_path")

    repo = pygit2.Repository(str(path))

    assert not repo.head_is_unborn
    assert repo.head.shorthand == "master"
