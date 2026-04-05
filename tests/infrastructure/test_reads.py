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


def test_get_staged_diff_empty_when_nothing_staged(repo_impl):
    hunks = repo_impl.get_staged_diff("README.md")
    assert hunks == []


def test_get_staged_diff_returns_hunks_after_staging(repo_path, repo_impl):
    (repo_path / "README.md").write_text("# Test Repo\nnew line\n")
    repo_impl.stage(["README.md"])
    hunks = repo_impl.get_staged_diff("README.md")
    assert len(hunks) >= 1
    all_lines = [line for h in hunks for line in h.lines]
    added_lines = [content for origin, content in all_lines if origin == "+"]
    assert any("new line" in line for line in added_lines)


def test_get_staged_diff_new_file_unborn_head(tmp_path):
    """get_staged_diff on a brand-new repo (no commits yet) shows staged new file."""
    import pygit2
    from git_gui.infrastructure.pygit2_repo import Pygit2Repository
    repo = pygit2.init_repository(str(tmp_path))
    (tmp_path / "new.txt").write_text("hello\n")
    repo.index.add("new.txt")
    repo.index.write()
    impl = Pygit2Repository(str(tmp_path))
    hunks = impl.get_staged_diff("new.txt")
    assert len(hunks) >= 1
    all_lines = [line for h in hunks for line in h.lines]
    added_lines = [content for origin, content in all_lines if origin == "+"]
    assert any("hello" in line for line in added_lines)


def test_get_commit_returns_commit(repo_impl):
    commits = repo_impl.get_commits(limit=1)
    oid = commits[0].oid
    commit = repo_impl.get_commit(oid)
    assert commit.oid == oid
    assert commit.message == "Initial commit"
    assert "Test User" in commit.author


def test_get_tags_empty(repo_impl):
    tags = repo_impl.get_tags()
    assert tags == []


def test_get_tags_lightweight(repo_path, repo_impl):
    raw = pygit2.Repository(str(repo_path))
    target = raw.head.target
    raw.references.create("refs/tags/v1.0.0", target)
    tags = repo_impl.get_tags()
    assert len(tags) == 1
    assert tags[0].name == "v1.0.0"
    assert tags[0].target_oid == str(target)
    assert tags[0].is_annotated is False
    assert tags[0].message is None


def test_get_remote_tags_no_remote(repo_impl):
    """Repos without remotes return an empty list."""
    tags = repo_impl.get_remote_tags("origin")
    assert tags == []


def test_get_tags_annotated(repo_path, repo_impl):
    raw = pygit2.Repository(str(repo_path))
    target = raw.head.target
    sig = pygit2.Signature("Tagger", "tagger@example.com")
    raw.create_tag("v2.0.0", target, pygit2.GIT_OBJECT_COMMIT, sig, "Release 2.0")
    tags = repo_impl.get_tags()
    annotated = [t for t in tags if t.name == "v2.0.0"]
    assert len(annotated) == 1
    assert annotated[0].is_annotated is True
    assert annotated[0].message == "Release 2.0"
    assert "Tagger" in annotated[0].tagger
