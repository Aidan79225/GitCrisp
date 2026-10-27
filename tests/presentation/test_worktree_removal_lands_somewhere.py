"""Removing the worktree you are standing in has to move you out of it.

It used to succeed and change nothing else: the active path, the window title
and the repo store all went on naming a directory that no longer existed, and
every read after that raised "head reference does not exist" until the user
clicked another repo themselves.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow
from git_gui.presentation.widgets.repo_list import _IS_ACTIVE_ROLE


@pytest.fixture
def window(qtbot, repo_path, tmp_path):
    from main import _open_session

    queries, commands = _open_session(str(repo_path))
    store = JsonRepoStore(tmp_path / "repos.json")
    w = MainWindow(
        queries,
        commands,
        store,
        JsonRemoteTagCache(),
        str(repo_path),
        session_factory=_open_session,
    )
    qtbot.addWidget(w)
    return w


def _existing(tmp_path, name: str) -> str:
    path = tmp_path / name
    path.mkdir(exist_ok=True)
    return str(path)


def _requests_recorded(window: MainWindow, monkeypatch) -> list[str]:
    """The paths the window asks to open, none of which is opened."""
    requested: list[str] = []
    monkeypatch.setattr(window, "_request_repo", lambda request: requested.append(request.path))
    return requested


# ── Where it lands ───────────────────────────────────────────────────────────


def test_removing_the_active_worktree_switches_to_the_repo_that_owned_it(
    window, tmp_path, monkeypatch
):
    owner = _existing(tmp_path, "owner")
    removed = str(tmp_path / "gone")  # deleted by the time we are called
    window._repo_path = removed
    window._repo_list.set_active_worktrees([], owner_path=owner)

    switched = _requests_recorded(window, monkeypatch)
    window._on_worktree_removed(removed)

    assert switched == [owner]


def test_removing_some_other_worktree_leaves_you_where_you_are(window, tmp_path, monkeypatch):
    owner = _existing(tmp_path, "owner")
    window._repo_path = owner
    window._repo_list.set_active_worktrees([], owner_path=owner)

    switched = _requests_recorded(window, monkeypatch)
    window._on_worktree_removed(str(tmp_path / "some-other-worktree"))

    assert switched == [], "only the worktree under you is worth moving out of"
    assert window._repo_path == owner


def test_the_removed_path_is_forgotten(window, tmp_path, monkeypatch):
    owner = _existing(tmp_path, "owner")
    removed = _existing(tmp_path, "gone")
    window._repo_store.add_open(removed)
    window._repo_path = owner
    _requests_recorded(window, monkeypatch)

    window._on_worktree_removed(removed)

    assert removed not in window._repo_store.get_open_repos()


def test_nothing_left_to_open_ends_in_the_empty_state(window, tmp_path, monkeypatch):
    removed = str(tmp_path / "gone")
    window._repo_path = removed
    window._repo_list.set_active_worktrees([], owner_path=None)
    window._worktree_paths_by_branch = {}
    window._repo_store.forget(str(window._repo_store.get_active() or ""))
    for path in list(window._repo_store.get_open_repos()):
        window._repo_store.forget(path)

    switched = _requests_recorded(window, monkeypatch)
    window._on_worktree_removed(removed)

    assert switched == []
    assert window._repo_path is None
    assert window.windowTitle() == "GitCrisp"


# ── Choosing the destination ─────────────────────────────────────────────────


def test_the_owner_wins_over_a_sibling_worktree(window, tmp_path):
    """A sibling would be an arbitrary choice; the owner is the same one every
    time, and is what the deleted worktree was a view of."""
    owner = _existing(tmp_path, "owner")
    sibling = _existing(tmp_path, "sibling")
    window._repo_list.set_active_worktrees([], owner_path=owner)
    window._worktree_paths_by_branch = {"feature": sibling}

    assert window._home_after_removing(str(tmp_path / "gone")) == owner


def test_a_sibling_is_used_when_the_owner_was_never_recorded(window, tmp_path):
    """Opening straight into a worktree never records one."""
    sibling = _existing(tmp_path, "sibling")
    window._repo_list.set_active_worktrees([], owner_path=None)
    window._worktree_paths_by_branch = {"feature": sibling}

    assert window._home_after_removing(str(tmp_path / "gone")) == sibling


def test_a_candidate_that_no_longer_exists_is_skipped(window, tmp_path):
    """The owner can have been deleted from disk while the app was open."""
    real = _existing(tmp_path, "still-here")
    window._repo_list.set_active_worktrees([], owner_path=str(tmp_path / "vanished"))
    window._worktree_paths_by_branch = {"feature": real}

    assert window._home_after_removing(str(tmp_path / "gone")) == real


def test_the_removed_path_is_never_the_destination(window, tmp_path):
    removed = _existing(tmp_path, "gone")  # still on disk, but being removed
    window._repo_list.set_active_worktrees([], owner_path=removed)
    window._worktree_paths_by_branch = {"feature": removed}
    for path in list(window._repo_store.get_open_repos()):
        window._repo_store.forget(path)

    assert window._home_after_removing(removed) is None


# ── Another open repo may sit on a share that is down ────────────────────────


def _probes_recorded(monkeypatch) -> list[str]:
    probed: list[str] = []
    is_dir = Path.is_dir

    def _recording(self: Path, *args, **kwargs) -> bool:
        probed.append(str(self))
        return is_dir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_dir", _recording)
    return probed


def _only_open_repo(window: MainWindow, path: str) -> None:
    window._repo_list.set_active_worktrees([], owner_path=None)
    window._worktree_paths_by_branch = {}
    for open_path in list(window._repo_store.get_open_repos()):
        window._repo_store.forget(open_path)
    window._repo_store.add_open(path)


def test_no_other_open_repo_is_looked_for_on_disk(window, tmp_path, monkeypatch):
    """Looking runs on the GUI thread: on a share that is down it waits out the
    network timeout, about 21 s on Windows, with the window frozen."""
    far = str(tmp_path / "on-a-share")
    _only_open_repo(window, far)
    probed = _probes_recorded(monkeypatch)

    assert window._home_after_removing(str(tmp_path / "gone")) == far
    assert far not in probed


def test_an_open_repo_that_will_not_open_leaves_the_window_empty(qtbot, window, tmp_path):
    """Not on the deleted worktree, where every read would fail."""
    removed = str(tmp_path / "gone")
    window._repo_path = removed
    _only_open_repo(window, str(tmp_path / "on-a-share"))

    with qtbot.waitSignal(window._repo_ready_signals.failed, timeout=5000):
        window._on_worktree_removed(removed)

    assert window._repo_path is None
    assert window.windowTitle() == "GitCrisp"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _repo_with_worktree(tmp_path) -> tuple[Path, str]:
    """Repo x, and its linked worktree x-feature."""
    main = tmp_path / "x"
    main.mkdir()
    _git(main, "init", "-q", "-b", "master", ".")
    _git(main, "config", "user.name", "T")
    _git(main, "config", "user.email", "t@e.com")
    (main / "a.txt").write_text("x\n")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-qm", "init")
    worktree = str(tmp_path / "x-feature")
    _git(main, "worktree", "add", "-q", "-b", "feature", worktree)
    return main, worktree


def _window_on(qtbot, worktree: str, store: JsonRepoStore, session_factory=None) -> MainWindow:
    from main import _open_session

    queries, commands = _open_session(worktree)
    win = MainWindow(
        queries,
        commands,
        store,
        JsonRemoteTagCache(),
        worktree,
        session_factory=session_factory or _open_session,
    )
    qtbot.addWidget(win)
    return win


def _open_rows(win: MainWindow) -> list[tuple[Path, bool]]:
    """Each open row's repo, and whether it is drawn as the one on screen."""
    model = win._repo_list._model
    header = model.item(0)
    if header is None or header.text() != "OPEN":
        return []
    rows = (header.child(row) for row in range(header.rowCount()))
    return [(Path(r.data(Qt.UserRole)), bool(r.data(_IS_ACTIVE_ROLE))) for r in rows]


def _git_removes_the_worktree(win: MainWindow, main: Path, worktree: str) -> None:
    """Remove *worktree* behind the window's back, as a terminal would.

    The window's change detector watches the worktree's gitdir, and on
    Windows a watched directory can refuse deletion for a moment, which made
    `git worktree remove` fail now and then under load. The tests are about
    what happens after the removal, so the watch is dropped first.
    """
    win._stop_change_detector()
    _git(main, "worktree", "remove", worktree)


def _remove_the_worktree_on_screen(qtbot, win: MainWindow, main: Path, worktree: str) -> None:
    _git_removes_the_worktree(win, main, worktree)
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._on_worktree_removed(worktree)


def _own_row_store(tmp_path, worktree: str) -> tuple[JsonRepoStore, str]:
    """The worktree opened on a row of its own, after a repo on a share."""
    far = str(tmp_path / "on-a-share")
    store = JsonRepoStore(tmp_path / "repos.json")
    store.add_open(worktree)
    store.add_open(far)
    return store, far


def test_a_worktree_opened_on_its_own_row_returns_to_its_main_worktree(
    qtbot, tmp_path, monkeypatch
):
    """Its owner is itself, and the main worktree is not an open repo: it went
    on to probe the open repos, and with none of them reachable, to nothing."""
    main, worktree = _repo_with_worktree(tmp_path)
    store, far = _own_row_store(tmp_path, worktree)
    win = _window_on(qtbot, worktree, store)
    probed = _probes_recorded(monkeypatch)

    _remove_the_worktree_on_screen(qtbot, win, main, worktree)

    assert Path(win._repo_path) == main.resolve()
    assert far not in probed


def test_the_main_worktree_takes_the_removed_worktrees_row(qtbot, tmp_path):
    """Landed there unlisted, it was in no row and under none: Ctrl+1..9 could
    not reach it, and the next click lost it until it was opened by hand."""
    main, worktree = _repo_with_worktree(tmp_path)
    store, far = _own_row_store(tmp_path, worktree)
    win = _window_on(qtbot, worktree, store)

    _remove_the_worktree_on_screen(qtbot, win, main, worktree)

    assert _open_rows(win) == [(Path(far), False), (main.resolve(), True)]
    assert store.get_open_repos() == [far, win._repo_path]


def test_a_worktree_with_no_row_and_no_open_repo_lands_on_a_listed_main_worktree(qtbot, tmp_path):
    """Relaunched onto a worktree whose repo was closed: no row, and no group."""
    main, worktree = _repo_with_worktree(tmp_path)
    far = str(tmp_path / "on-a-share")
    store = JsonRepoStore(tmp_path / "repos.json")
    store.add_open(far)
    store.set_active(worktree)
    win = _window_on(qtbot, worktree, store)

    _remove_the_worktree_on_screen(qtbot, win, main, worktree)

    assert _open_rows(win) == [(main.resolve(), True), (Path(far), False)]


def test_a_main_worktree_that_will_not_open_is_not_listed(qtbot, tmp_path):
    """Listing waits for the open: one that fails leaves the window empty, as
    any repo replacing the one on screen does, and lists nothing."""
    from main import _open_session

    main, worktree = _repo_with_worktree(tmp_path)
    store, far = _own_row_store(tmp_path, worktree)

    def _main_will_not_open(path: str):
        if Path(path) == main.resolve():
            raise OSError("access is denied")
        return _open_session(path)

    win = _window_on(qtbot, worktree, store, session_factory=_main_will_not_open)
    _git_removes_the_worktree(win, main, worktree)

    with qtbot.waitSignal(win._repo_ready_signals.failed, timeout=5000):
        win._on_worktree_removed(worktree)

    assert win._repo_path is None
    assert store.get_open_repos() == [far]
