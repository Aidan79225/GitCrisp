import pytest
import pygit2
from pathlib import Path


@pytest.fixture
def repo_path(tmp_path) -> Path:
    """Creates a temp git repo with one commit on 'master'."""
    repo = pygit2.init_repository(str(tmp_path))
    sig = pygit2.Signature("Test User", "test@example.com")
    (tmp_path / "README.md").write_text("# Test Repo\n")
    repo.index.add("README.md")
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("refs/heads/master", sig, sig, "Initial commit", tree, [])
    return tmp_path


@pytest.fixture
def repo_impl(repo_path):
    from git_gui.infrastructure.pygit2_repo import Pygit2Repository
    return Pygit2Repository(str(repo_path))
