"""The graph walks the current branch's upstream as well as HEAD.

A branch behind its upstream then shows the commits it has yet to pull. An
upstream git cannot look up must not cost the user the rest of the graph.
"""

import pygit2

from git_gui.infrastructure.pygit2 import Pygit2Repository


def _track_origin_master(repo: pygit2.Repository, merge_ref: str = "refs/heads/master") -> None:
    repo.config["remote.origin.url"] = "https://example.invalid/repo.git"
    repo.config["remote.origin.fetch"] = "+refs/heads/*:refs/remotes/origin/*"
    repo.config["branch.master.remote"] = "origin"
    repo.config["branch.master.merge"] = merge_ref


def _commit_on_origin_master(repo: pygit2.Repository) -> str:
    sig = pygit2.Signature("Test User", "test@example.com")
    head = repo.head.target
    tree = repo[head].tree.id
    oid = repo.create_commit("refs/remotes/origin/master", sig, sig, "not pulled yet", tree, [head])
    return str(oid)


def test_a_commit_only_on_the_upstream_is_in_the_page(repo_path):
    repo = pygit2.Repository(str(repo_path))
    _track_origin_master(repo)
    upstream_only = _commit_on_origin_master(repo)

    page = Pygit2Repository(str(repo_path)).get_commits(limit=10)

    assert upstream_only in {c.oid for c in page}


def test_an_upstream_git_cannot_parse_still_leaves_the_head_s_history(repo_path):
    repo = pygit2.Repository(str(repo_path))
    _track_origin_master(repo, merge_ref="refs/heads/bad..name")
    head = str(repo.head.target)

    page = Pygit2Repository(str(repo_path)).get_commits(limit=10)

    assert [c.oid for c in page] == [head]
