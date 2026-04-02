import pygit2
import pytest
from pathlib import Path
from git_gui.domain.entities import WORKING_TREE_OID
from git_gui.infrastructure.pygit2_repo import Pygit2Repository


def test_get_commits_returns_initial_commit(repo_impl):
    commits = repo_impl.get_commits(limit=10)
    assert len(commits) == 1
    assert commits[0].message == "Initial commit"
    assert commits[0].parents == []


def test_get_commits_oid_is_string(repo_impl):
    commits = repo_impl.get_commits(limit=10)
    assert isinstance(commits[0].oid, str)
    assert len(commits[0].oid) == 40


def test_get_commits_respects_limit(repo_path):
    repo = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    # add a second commit
    (repo_path / "b.txt").write_text("b")
    repo.index.add("b.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    head_oid = repo.head.target
    repo.create_commit("refs/heads/master", sig, sig, "Second commit", tree, [head_oid])

    impl = Pygit2Repository(str(repo_path))
    commits = impl.get_commits(limit=1)
    assert len(commits) == 1
    assert commits[0].message == "Second commit"


def test_get_branches_returns_master(repo_impl):
    branches = repo_impl.get_branches()
    names = [b.name for b in branches]
    assert "master" in names


def test_get_branches_head_is_marked(repo_impl):
    branches = repo_impl.get_branches()
    head_branches = [b for b in branches if b.is_head]
    assert len(head_branches) == 1
    assert head_branches[0].name == "master"


def test_get_working_tree_empty_on_clean_repo(repo_impl):
    files = repo_impl.get_working_tree()
    assert files == []


def test_get_working_tree_detects_untracked(repo_path, repo_impl):
    (repo_path / "untracked.txt").write_text("new")
    files = repo_impl.get_working_tree()
    paths = [f.path for f in files]
    assert "untracked.txt" in paths
    untracked = next(f for f in files if f.path == "untracked.txt")
    assert untracked.status == "untracked"


def test_get_working_tree_detects_modified(repo_path, repo_impl):
    (repo_path / "README.md").write_text("modified content\n")
    files = repo_impl.get_working_tree()
    modified = next((f for f in files if f.path == "README.md"), None)
    assert modified is not None
    assert modified.status == "unstaged"
    assert modified.delta == "modified"


def test_get_commit_files_initial_commit(repo_impl):
    commits = repo_impl.get_commits(limit=1)
    files = repo_impl.get_commit_files(commits[0].oid)
    paths = [f.path for f in files]
    assert "README.md" in paths


def test_get_stashes_empty(repo_impl):
    stashes = repo_impl.get_stashes()
    assert stashes == []


def test_get_file_diff_initial_commit(repo_impl):
    commits = repo_impl.get_commits(limit=1)
    hunks = repo_impl.get_file_diff(commits[0].oid, "README.md")
    assert len(hunks) >= 1
    all_lines = [line for h in hunks for line in h.lines]
    added_lines = [content for origin, content in all_lines if origin == "+"]
    assert any("Test Repo" in line for line in added_lines)
