import pygit2
import pytest
from pathlib import Path


def _is_git_repo(path: str) -> bool:
    return pygit2.discover_repository(path) is not None


class TestIsGitRepo:
    def test_returns_true_for_valid_repo(self, tmp_path):
        pygit2.init_repository(str(tmp_path))
        assert _is_git_repo(str(tmp_path)) is True

    def test_returns_false_for_plain_directory(self, tmp_path):
        assert _is_git_repo(str(tmp_path)) is False

    def test_returns_false_for_nonexistent_path(self, tmp_path):
        assert _is_git_repo(str(tmp_path / "nope")) is False


from git_gui.infrastructure.repo_store import JsonRepoStore


class TestFindValidRepoPruning:
    def test_prunes_non_git_directory_from_store(self, tmp_path):
        """A stored path that exists as a dir but is not a git repo gets pruned."""
        plain_dir = tmp_path / "not_a_repo"
        plain_dir.mkdir()

        store_path = tmp_path / "repos.json"
        store = JsonRepoStore(store_path)
        store.load()
        store.add_open(str(plain_dir))
        store.save()

        from main import _find_valid_repo

        result = _find_valid_repo(store)
        assert result is None
        assert str(plain_dir) not in store.get_open_repos()

    def test_returns_valid_git_repo(self, tmp_path):
        """A stored path that is a valid git repo is returned."""
        repo_dir = tmp_path / "real_repo"
        repo_dir.mkdir()
        pygit2.init_repository(str(repo_dir))

        store_path = tmp_path / "repos.json"
        store = JsonRepoStore(store_path)
        store.load()
        store.add_open(str(repo_dir))
        store.save()

        from main import _find_valid_repo

        result = _find_valid_repo(store)
        assert result == str(repo_dir)
