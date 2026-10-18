"""TagOps: reading local tags and listing a remote's tags."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


def test_an_annotated_tag_of_a_tree_does_not_hide_the_other_tags(repo_path):
    # git.git's junio-gpg-pub tags a blob and linux's v2.6.11-tree a tree.
    raw = pygit2.Repository(str(repo_path))
    head = raw.head.peel(pygit2.Commit)
    sig = pygit2.Signature("Tagger", "tagger@example.com")
    raw.create_tag("tree-tag", head.tree_id, pygit2.GIT_OBJECT_TREE, sig, "a tree")
    raw.create_tag("v1", head.id, pygit2.GIT_OBJECT_COMMIT, sig, "release")

    tags = Pygit2Repository(str(repo_path)).get_tags()

    assert [(t.name, t.target_oid) for t in tags] == [("v1", str(head.id))]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def with_origin(repo_path: Path, tmp_path: Path) -> Path:
    """repo_path with an empty bare repository as `origin`."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    _git(repo_path, "remote", "add", "origin", str(remote))
    return repo_path


def test_a_non_ascii_remote_tag_does_not_hide_the_others(with_origin):
    # git prints "Ł" as UTF-8, which neither cp1252 nor cp950 can decode.
    _git(with_origin, "tag", "v1.0")
    _git(with_origin, "tag", "Łódź")
    _git(with_origin, "push", "-q", "origin", "--tags")

    tags = Pygit2Repository(str(with_origin)).get_remote_tags("origin")

    assert sorted(tags) == ["v1.0", "Łódź"]
