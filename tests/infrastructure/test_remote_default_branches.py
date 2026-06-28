from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


@pytest.fixture
def writable_repo(repo_path) -> tuple[Pygit2Repository, Path]:
    return Pygit2Repository(str(repo_path)), repo_path


def test_remote_default_branches_resolves_symref(writable_repo):
    impl, path = writable_repo
    raw = pygit2.Repository(str(path))
    head_oid = raw.head.target
    raw.remotes.create("origin", "https://example.test/r.git")
    raw.references.create("refs/remotes/origin/main", head_oid)
    raw.references.create("refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    assert impl.remote_default_branches() == {"origin": "origin/main"}


def test_remote_default_branches_skips_remote_without_head(writable_repo):
    impl, path = writable_repo
    raw = pygit2.Repository(str(path))
    raw.remotes.create("origin", "https://example.test/r.git")
    raw.references.create("refs/remotes/origin/main", raw.head.target)
    # No refs/remotes/origin/HEAD symref created.

    assert impl.remote_default_branches() == {}
