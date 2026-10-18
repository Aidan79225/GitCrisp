"""The window main.py opens at launch, over the repo store the last session left.

Built through ``main._open_window`` with a real store, real repositories and a
real window, so what is checked is what the next launch will see.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
import pytest
from PySide6.QtCore import Qt

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


@pytest.fixture
def start_window(qtbot, tmp_path):
    """The startup window itself, over a store that holds *open_paths* and *active*."""
    windows = []

    def _start(open_paths: list[Path], active: Path):
        store = JsonRepoStore(tmp_path / "repos.json")
        store.load()
        for path in reversed(open_paths):
            store.add_open(str(path))
        store.set_active(str(active))
        window = app_main._open_window(store, JsonRemoteTagCache(tmp_path / "remote_tags"))
        qtbot.addWidget(window)
        windows.append(window)
        return window

    yield _start

    for window in windows:
        window._stop_change_detector()
    qtbot.wait(200)


def _repo_row(window, path: Path):
    model = window._repo_list._model
    for section in (model.item(row) for row in range(model.rowCount())):
        for row in range(section.rowCount()):
            if section.child(row).data(Qt.UserRole) == str(path):
                return section.child(row).index()
    raise AssertionError(f"no repo row for {path}")


def _broken_repo(make_repo, name: str) -> Path:
    """A repo discover_repository accepts but pygit2 will not open."""
    path = make_repo(name)
    (path / ".git" / "config").write_text("[core\n", encoding="utf-8")
    return path


def test_an_active_repo_that_will_not_open_yields_to_the_next_open_one(make_repo, start_window):
    broken = _broken_repo(make_repo, "broken")
    good = make_repo("good")

    window = start_window(open_paths=[broken, good], active=broken)

    assert window._repo_path == str(good)
    assert window._repo_store.get_active() == str(good)


def test_an_active_repo_that_will_not_open_can_still_be_clicked(make_repo, start_window, qtbot):
    """Clicking it is how the user retries it and sees why it failed."""
    broken = _broken_repo(make_repo, "broken")
    good = make_repo("good")
    window = start_window(open_paths=[broken, good], active=broken)

    with qtbot.waitSignal(window._repo_list.repo_switch_requested, timeout=1000) as switch:
        window._repo_list._on_item_clicked(_repo_row(window, broken))

    assert switch.args == [str(broken)]


def test_repos_pruned_after_launch_leave_the_repo_list(make_repo, tmp_path, start_window):
    """The pruning finishes after the window has drawn the list from the store."""
    good = make_repo("good")
    deleted = make_repo("deleted")
    window = start_window(open_paths=[good, deleted], active=good)
    window._repo_store.forget(str(deleted))

    app_main._reload_repo_list(window)

    model = window._repo_list._model
    sections = [model.item(row) for row in range(model.rowCount())]
    listed = {s.child(row).data(Qt.UserRole) for s in sections for row in range(s.rowCount())}
    assert listed == {str(good)}
