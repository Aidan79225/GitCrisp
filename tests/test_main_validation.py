import pygit2

from main import _is_git_repo


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

    def test_prunes_active_non_git_directory(self, tmp_path):
        """Active path that is a dir but not a git repo gets pruned."""
        plain_dir = tmp_path / "not_a_repo"
        plain_dir.mkdir()

        store_path = tmp_path / "repos.json"
        store = JsonRepoStore(store_path)
        store.load()
        store.add_open(str(plain_dir))  # This also sets active
        store.save()

        from main import _find_valid_repo

        result = _find_valid_repo(store)
        assert result is None
        assert store.get_active() is None

    def test_prunes_dead_open_repo_when_active_is_valid(self, tmp_path):
        """A dead path deeper in the open list is pruned even when the active
        repo is valid.

        Regression: a deleted worktree lingered in the open list across sessions
        because pruning short-circuited as soon as the (valid) active repo was
        found, leaving later stale entries in place to fail on switch.
        """
        valid_repo = tmp_path / "valid_repo"
        valid_repo.mkdir()
        pygit2.init_repository(str(valid_repo))
        dead = tmp_path / "deleted_worktree"  # never created on disk

        store_path = tmp_path / "repos.json"
        store = JsonRepoStore(store_path)
        store.load()
        store.add_open(str(dead))        # dead entry, deeper in the list
        store.add_open(str(valid_repo))  # add_open sets this as active
        store.save()
        assert store.get_active() == str(valid_repo)
        assert str(dead) in store.get_open_repos()

        from main import _find_valid_repo

        result = _find_valid_repo(store)

        assert result == str(valid_repo)
        assert str(dead) not in store.get_open_repos()
        assert str(dead) not in store.get_recent_repos()

    def test_keeps_valid_active_not_in_open_list(self, tmp_path):
        """A valid active repo is returned even when it isn't in the open list
        (e.g. an active worktree recorded via set_active without add_open)."""
        in_open = tmp_path / "open_repo"
        in_open.mkdir()
        pygit2.init_repository(str(in_open))
        worktree = tmp_path / "active_worktree"
        worktree.mkdir()
        pygit2.init_repository(str(worktree))

        store_path = tmp_path / "repos.json"
        store = JsonRepoStore(store_path)
        store.load()
        store.add_open(str(in_open))
        store.set_active(str(worktree))  # active, but not added to open
        store.save()
        assert str(worktree) not in store.get_open_repos()

        from main import _find_valid_repo

        result = _find_valid_repo(store)

        assert result == str(worktree)

    def test_prunes_dead_recent_repo(self, tmp_path):
        """A dead path in the recent list is forgotten, not just left to fail."""
        valid_repo = tmp_path / "valid_repo"
        valid_repo.mkdir()
        pygit2.init_repository(str(valid_repo))
        dead = tmp_path / "deleted_worktree"

        store_path = tmp_path / "repos.json"
        store = JsonRepoStore(store_path)
        store.load()
        store.add_open(str(dead))
        store.close_repo(str(dead))  # moves dead into recent
        store.add_open(str(valid_repo))
        store.save()
        assert str(dead) in store.get_recent_repos()

        from main import _find_valid_repo

        _find_valid_repo(store)

        assert str(dead) not in store.get_recent_repos()
