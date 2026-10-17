"""A new branch can start from any revision the user types, not only an
object id: HEAD, a tag, a branch name or an expression such as master~1."""

from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


@pytest.fixture
def two_commits(repo_path: Path) -> tuple[Pygit2Repository, dict[str, str]]:
    """master has a first and a second commit; the first is tagged v1, annotated."""
    impl = Pygit2Repository(str(repo_path))
    first = impl.get_head_oid()
    sig = impl._repo.default_signature
    impl._repo.create_tag("v1", pygit2.Oid(hex=first), pygit2.GIT_OBJECT_COMMIT, sig, "v1\n")
    (repo_path / "f.txt").write_text("f\n")
    impl.stage(["f.txt"])
    second = impl.commit("second").oid
    return impl, {"first": first, "second": second}


@pytest.mark.parametrize(
    ("start_point", "expected"),
    [("HEAD", "second"), ("master~1", "first"), ("v1", "first")],
)
def test_a_branch_starts_at_the_commit_a_revision_names(two_commits, start_point, expected):
    impl, commits = two_commits

    branch = impl.create_branch("topic", start_point)

    assert str(impl._repo.branches.local["topic"].target) == commits[expected]
    assert branch.target_oid == commits[expected]
