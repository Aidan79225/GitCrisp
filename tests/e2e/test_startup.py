"""The window main.py opens at launch, over the repo store the last session left.

Built through ``main._open_window`` with a real store, real repositories and a
real window, so what is checked is what the next launch will see.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
import pytest

import main as app_main
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore


@pytest.fixture
def launch(qtbot, tmp_path):
    """Open the startup window over a store that holds *open_paths* and *active*."""
    windows = []

    def _launch(open_paths: list[Path], active: Path) -> JsonRepoStore:
        store = JsonRepoStore(tmp_path / "repos.json")
        store.load()
        for path in reversed(open_paths):
            store.add_open(str(path))
        store.set_active(str(active))
        store.save()
        window = app_main._open_window(store, JsonRemoteTagCache(tmp_path / "remote_tags"))
        qtbot.addWidget(window)
        windows.append(window)
        reloaded = JsonRepoStore(tmp_path / "repos.json")
        reloaded.load()
        return reloaded

    yield _launch

    for window in windows:
        window._stop_change_detector()
    qtbot.wait(200)


def test_an_active_linked_worktree_is_not_promoted_into_the_open_list(make_repo, tmp_path, launch):
    """Switching to a worktree records it as active without opening it; the
    next launch must not turn it into a top-level open repo of its own."""
    main_repo = make_repo("main")
    repo = pygit2.Repository(str(main_repo))
    repo.branches.local.create("feat", repo.head.peel(pygit2.Commit))
    linked = tmp_path / "linked"
    repo.add_worktree("linked", str(linked), repo.branches.local["feat"])

    store = launch(open_paths=[main_repo], active=linked)

    assert store.get_open_repos() == [str(main_repo)]
    assert store.get_active() == str(linked)
