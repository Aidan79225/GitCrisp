"""Fixtures that assemble the real application stack — no test doubles.

Every other presentation test builds ``MainWindow`` on ``MagicMock`` buses, so
none of them notices when the wiring between layers drifts: a renamed query, a
changed entity field, or an adapter that no longer satisfies a port passes a
mocked test and crashes the shipped app. These fixtures build what ``main.py``
builds — a real ``Pygit2Repository`` behind real buses behind a real window,
over a real git repository on disk.

The session factory used here is ``main._open_session`` itself, so the tests
exercise production wiring rather than a copy of it.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
import pytest

import main as app_main
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow
from git_gui.presentation.widgets.avatar_loader import get_avatar_loader

# Generous enough for a cold CI runner, short enough that a genuine hang fails
# the test rather than stalling the job.
TIMEOUT = 10_000

_NAME = "Test User"
_EMAIL = "test@example.com"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Keep the window off the network.

    ``MainWindow.__init__`` starts a GitHub release check and the commit rows
    fetch Gravatar images. Both are opt-out rather than off, and neither
    belongs in a test.
    """
    monkeypatch.setattr(
        "git_gui.presentation.app_settings.get_check_updates",
        lambda: False,
    )
    # The avatar loader is a process-wide singleton whose `enabled` flag is
    # broadcast to every live widget; flipping it would fire that signal at
    # widgets a previous test already destroyed. Cutting the fetch instead
    # leaves the loader's behaviour intact and reaches no network.
    monkeypatch.setattr(get_avatar_loader(), "_start_fetch", lambda email_hash: None)


@pytest.fixture
def make_repo(tmp_path):
    """Build a real git repo with `commits` commits on master.

    The initial branch is pinned so a contributor whose git sets
    `init.defaultBranch` still gets the branch the assertions name.
    """

    def _make(name: str, commits: int = 1) -> Path:
        path = tmp_path / name
        path.mkdir()
        repo = pygit2.init_repository(str(path), initial_head="master")
        repo.config["user.name"] = _NAME
        repo.config["user.email"] = _EMAIL
        for n in range(commits):
            write_commit(path, f"file{n}.txt", f"content {n}\n", f"Commit {n}")
        return path

    return _make


def write_commit(repo_dir: Path, filename: str, content: str, message: str) -> str:
    """Write a file and commit it on the current branch. Returns the new OID."""
    repo = pygit2.Repository(str(repo_dir))
    (repo_dir / filename).write_text(content)
    repo.index.add(filename)
    repo.index.write()
    tree = repo.index.write_tree()
    sig = pygit2.Signature(_NAME, _EMAIL)
    parents = [] if repo.head_is_unborn else [repo.head.target]
    # An unborn HEAD cannot be committed to by name; write to the branch it
    # points at instead.
    ref = repo.lookup_reference("HEAD").target if repo.head_is_unborn else "HEAD"
    return str(repo.create_commit(ref, sig, sig, message, tree, parents))


@pytest.fixture
def make_window(qtbot, tmp_path):
    """Open a MainWindow over a real repo (or none, for the empty state).

    Mirrors main.main(): a real repo store, a real remote-tag cache, real
    buses over a real Pygit2Repository, and main's own session factory.
    """
    windows: list[MainWindow] = []

    def _make(repo_dir: Path | None) -> MainWindow:
        store = JsonRepoStore(tmp_path / "repos.json")
        store.load()
        if repo_dir is not None:
            store.add_open(str(repo_dir))
            store.set_active(str(repo_dir))
        store.save()

        if repo_dir is None:
            queries, commands = None, None
        else:
            queries, commands = app_main._open_session(str(repo_dir))

        window = MainWindow(
            queries,
            commands,
            store,
            JsonRemoteTagCache(tmp_path / "remote_tags"),
            str(repo_dir) if repo_dir is not None else None,
            session_factory=app_main._open_session,
        )
        qtbot.addWidget(window)
        window.show()
        windows.append(window)
        return window

    yield _make

    for window in windows:
        # A repo switch leaves a filesystem watcher running; stop it before the
        # window goes away, then drain the event loop so any worker thread
        # still in flight emits into a live object rather than a deleted one.
        window._stop_change_detector()
    qtbot.wait(200)
