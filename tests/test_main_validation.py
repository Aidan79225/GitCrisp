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


def _startup_repo(store: JsonRepoStore) -> str | None:
    """The path main.py starts the window on."""
    from main import _open_startup_repo

    started = _open_startup_repo(store)
    return started.path if started else None


def _prune_in_background(store: JsonRepoStore, qtbot) -> None:
    """Run the pruning main.py starts once the window is up, and wait for it."""
    from main import _GoneRepoPruner

    pruned: list[bool] = []
    pruner = _GoneRepoPruner(store, save=store.save, on_pruned=lambda: pruned.append(True))
    pruner.start()
    qtbot.waitUntil(lambda: pruned == [True], timeout=5000)


def _repo(path):
    path.mkdir(parents=True)
    pygit2.init_repository(str(path))
    return path


def _store(tmp_path, open_paths=(), recent_paths=(), active=None) -> JsonRepoStore:
    """A store listing *open_paths* in that order, then *recent_paths*."""
    store = JsonRepoStore(tmp_path / "repos.json")
    store.load()
    for path in recent_paths:
        store.add_open(str(path))
        store.close_repo(str(path))
    for path in reversed(open_paths):
        store.add_open(str(path))
    if active is not None:
        store.set_active(str(active))
    return store


def _probes_recorded(monkeypatch) -> list[str]:
    import main

    probed: list[str] = []
    probe = main._stored_repo_state
    monkeypatch.setattr(main, "_stored_repo_state", lambda p: probed.append(p) or probe(p))
    return probed


class TestOpenStartupRepoPruning:
    def test_prunes_non_git_directory_from_store(self, tmp_path):
        """A stored path that exists as a dir but is not a git repo gets pruned."""
        plain_dir = tmp_path / "not_a_repo"
        plain_dir.mkdir()

        store_path = tmp_path / "repos.json"
        store = JsonRepoStore(store_path)
        store.load()
        store.add_open(str(plain_dir))
        store.save()

        result = _startup_repo(store)
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

        result = _startup_repo(store)
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

        result = _startup_repo(store)
        assert result is None
        assert store.get_active() is None

    def test_prunes_dead_open_repo_when_active_is_valid(self, tmp_path, qtbot):
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
        store.add_open(str(dead))  # dead entry, deeper in the list
        store.add_open(str(valid_repo))  # add_open sets this as active
        store.save()
        assert store.get_active() == str(valid_repo)
        assert str(dead) in store.get_open_repos()

        assert _startup_repo(store) == str(valid_repo)
        _prune_in_background(store, qtbot)

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

        result = _startup_repo(store)

        assert result == str(worktree)

    def test_prunes_dead_recent_repo(self, tmp_path, qtbot):
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

        _prune_in_background(store, qtbot)

        assert str(dead) not in store.get_recent_repos()


class TestOpenStartupSession:
    def test_a_repo_that_validates_but_will_not_open_starts_without_a_session(self, tmp_path):
        """discover_repository accepts a repo whose config does not parse, but
        opening it raises — which used to escape main() on every launch."""
        pygit2.init_repository(str(tmp_path))
        (tmp_path / ".git" / "config").write_text("[core\n", encoding="utf-8")
        assert _is_git_repo(str(tmp_path))

        from main import _open_startup_session

        assert _open_startup_session(str(tmp_path)) is None

    def test_a_repo_that_opens_starts_with_its_session(self, tmp_path):
        pygit2.init_repository(str(tmp_path))

        from main import _open_startup_session

        assert _open_startup_session(str(tmp_path)) is not None


class TestOpenStartupRepoKeepsUnreachablePaths:
    """A repo on a drive, share or mount that is not there right now is out of
    reach, not gone: its parent is missing too, unlike a deleted worktree's."""

    def test_an_open_repo_on_a_missing_volume_stays_open(self, tmp_path):
        valid = _repo(tmp_path / "valid")
        offline = tmp_path / "unmounted" / "work" / "project"
        store = _store(tmp_path, open_paths=[valid, offline], active=valid)

        assert _startup_repo(store) == str(valid)
        assert store.get_open_repos() == [str(valid), str(offline)]

    def test_a_recent_repo_on_a_missing_volume_stays_recent(self, tmp_path):
        valid = _repo(tmp_path / "valid")
        offline = tmp_path / "unmounted" / "work" / "project"
        store = _store(tmp_path, open_paths=[valid], recent_paths=[offline])

        _startup_repo(store)

        assert store.get_recent_repos() == [str(offline)]

    def test_an_active_repo_on_a_missing_volume_yields_to_the_next_open_one(self, tmp_path):
        valid = _repo(tmp_path / "valid")
        offline = tmp_path / "unmounted" / "work" / "project"
        store = _store(tmp_path, open_paths=[offline, valid], active=offline)

        assert _startup_repo(store) == str(valid)
        assert store.get_open_repos() == [str(offline), str(valid)]

    def test_each_stored_path_is_probed_once(self, tmp_path, monkeypatch):
        """On an unreachable share every probe waits out a network timeout,
        about ten seconds on Windows, and the launch waits with it."""
        valid = _repo(tmp_path / "valid")
        offline = tmp_path / "unmounted" / "work" / "project"
        store = _store(tmp_path, open_paths=[offline, valid], active=offline)
        probed = _probes_recorded(monkeypatch)

        _startup_repo(store)

        assert sorted(probed) == sorted({str(offline), str(valid)})


class TestStartupProbesOnlyWhatItOpens:
    """Startup runs before the window shows, and each probe of a path on an
    unreachable share waits out a network timeout, about twenty seconds on
    Windows, with nothing on screen."""

    def test_a_recent_repo_is_not_probed_before_the_window(self, tmp_path, monkeypatch):
        valid = _repo(tmp_path / "valid")
        offline = tmp_path / "unmounted" / "work" / "project"
        store = _store(tmp_path, open_paths=[valid], recent_paths=[offline])
        probed = _probes_recorded(monkeypatch)

        assert _startup_repo(store) == str(valid)

        assert str(offline) not in probed

    def test_open_repos_after_the_one_that_opens_are_not_probed(self, tmp_path, monkeypatch):
        valid = _repo(tmp_path / "valid")
        offline = tmp_path / "unmounted" / "work" / "project"
        store = _store(tmp_path, open_paths=[valid, offline])
        probed = _probes_recorded(monkeypatch)

        _startup_repo(store)

        assert probed == [str(valid)]

    def test_the_pruning_after_launch_keeps_repos_out_of_reach(self, tmp_path, qtbot):
        valid = _repo(tmp_path / "valid")
        dead = tmp_path / "deleted_worktree"
        offline_open = tmp_path / "unmounted" / "work" / "open"
        offline_recent = tmp_path / "unmounted" / "work" / "recent"
        store = _store(
            tmp_path, open_paths=[valid, offline_open, dead], recent_paths=[offline_recent]
        )

        _prune_in_background(store, qtbot)

        assert store.get_open_repos() == [str(valid), str(offline_open)]
        assert store.get_recent_repos() == [str(offline_recent)]


def _while_probing(path, monkeypatch, meanwhile) -> None:
    """Run *meanwhile* as the pruning probes *path*: what the user does while
    that probe waits out a network timeout on an unreachable share."""
    import main

    probe = main._stored_repo_state

    def probe_meanwhile(probed: str):
        if probed == str(path):
            meanwhile()
        return probe(probed)

    monkeypatch.setattr(main, "_stored_repo_state", probe_meanwhile)


class TestPruningKeepsWhatIsBackBeforeItEnds:
    """The pruning reports once every stored path is probed, minutes after
    launch with a share out of reach, so a path it found gone at the start may
    be a repo again by then: cloned back, or re-added as a worktree, and
    opened."""

    @staticmethod
    def _store_probing_reborn_first(tmp_path, reborn, offline) -> JsonRepoStore:
        valid = _repo(tmp_path / "valid")
        dead = tmp_path / "deleted_worktree"
        # Probed in this order: reborn before the share that holds the probe.
        return _store(tmp_path, open_paths=[valid, dead], recent_paths=[offline, reborn])

    def test_a_repo_opened_meanwhile_stays_open(self, tmp_path, qtbot, monkeypatch):
        reborn = tmp_path / "recloned"
        offline = tmp_path / "unmounted" / "work" / "project"
        store = self._store_probing_reborn_first(tmp_path, reborn, offline)

        def reopen():
            _repo(reborn)
            store.add_open(str(reborn))

        _while_probing(offline, monkeypatch, reopen)

        _prune_in_background(store, qtbot)

        assert store.get_open_repos() == [str(reborn), str(tmp_path / "valid")]
        assert store.get_active() == str(reborn)

    def test_a_repo_cloned_back_meanwhile_stays_listed(self, tmp_path, qtbot, monkeypatch):
        reborn = tmp_path / "recloned"
        offline = tmp_path / "unmounted" / "work" / "project"
        store = self._store_probing_reborn_first(tmp_path, reborn, offline)
        _while_probing(offline, monkeypatch, lambda: _repo(reborn))

        _prune_in_background(store, qtbot)

        assert store.get_recent_repos() == [str(reborn), str(offline)]

    def test_the_repo_on_screen_is_kept_until_the_next_launch(self, tmp_path, qtbot):
        """Forgetting it would drop it from the list while its panes are up."""
        valid = _repo(tmp_path / "valid")
        on_screen = tmp_path / "deleted_since_it_opened"
        dead = tmp_path / "deleted_worktree"
        store = _store(tmp_path, open_paths=[on_screen, valid, dead])
        store.set_active(str(on_screen))

        _prune_in_background(store, qtbot)

        assert store.get_open_repos() == [str(on_screen), str(valid)]
        assert store.get_active() == str(on_screen)


class TestAGitFileThatCannotBeFollowed:
    """An interrupted submodule checkout or a sync-tool conflict can leave a
    .git file empty, and discover_repository raises on it rather than
    answering. The folder is still a repo to keep, like one that will not
    open, not a reason to stop the launch or the pruning."""

    @staticmethod
    def _malformed(path):
        path.mkdir()
        (path / ".git").write_bytes(b"")
        return path

    def test_the_pruning_keeps_it_and_forgets_what_is_gone(self, tmp_path, qtbot):
        valid = _repo(tmp_path / "valid")
        malformed = self._malformed(tmp_path / "malformed")
        dead = tmp_path / "deleted_worktree"
        store = _store(tmp_path, open_paths=[valid], recent_paths=[dead, malformed])

        _prune_in_background(store, qtbot)

        assert store.get_recent_repos() == [str(malformed)]

    def test_the_launch_passes_over_it_to_the_next_open_repo(self, tmp_path):
        valid = _repo(tmp_path / "valid")
        malformed = self._malformed(tmp_path / "malformed")
        store = _store(tmp_path, open_paths=[malformed, valid])
        store.set_active(str(malformed))

        assert _startup_repo(store) == str(valid)
        assert store.get_open_repos() == [str(malformed), str(valid)]
