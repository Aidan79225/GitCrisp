"""TagOps: reading local tags and listing a remote's tags."""

from __future__ import annotations

import pygit2

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
