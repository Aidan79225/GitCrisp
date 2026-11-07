"""Removing the worktree you are standing in has to move you out of it.

It used to succeed and change nothing else: the active path, the window title
and the repo store all went on naming a directory that no longer existed, and
every read after that raised "head reference does not exist" until the user
clicked another repo themselves.
"""

from __future__ import annotations

import os
import subprocess
import threading
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


def _wait_for_the_start_up_loads(qtbot, win: MainWindow) -> None:
    """Wait out the reads a new window starts on its own.

    The graph's dirty check runs `git status` in the worktree, and Windows will
    not delete a folder a process is running in.
    """
    qtbot.waitUntil(lambda: not win._graph._loading, timeout=10000)


def _git_removes_the_worktree(qtbot, win: MainWindow, main: Path, worktree: str) -> None:
    """Remove *worktree* behind the window's back, as a terminal would.

    Windows will not delete a folder a process is running in, and the window
    runs git in its worktree: in the loads it starts with, and in the reloads
    its change detector schedules. `git worktree remove` failed now and then
    with 'Permission denied' when it overlapped one. The tests are about what
    happens after the removal, so the detector is dropped and the loads are
    waited out first.
    """
    win._stop_change_detector()
    _wait_for_the_start_up_loads(qtbot, win)
    _git(main, "worktree", "remove", worktree)


def _remove_the_worktree_on_screen(qtbot, win: MainWindow, main: Path, worktree: str) -> None:
    _git_removes_the_worktree(qtbot, win, main, worktree)
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
    _git_removes_the_worktree(qtbot, win, main, worktree)

    with qtbot.waitSignal(win._repo_ready_signals.failed, timeout=5000):
        win._on_worktree_removed(worktree)

    assert win._repo_path is None
    assert store.get_open_repos() == [far]


# ── The window lets go of the worktree before git deletes it ─────────────────


def _quiet(qtbot, win: MainWindow) -> None:
    """Let the loads still under way finish: a worker must not outlive its test."""
    win._stop_change_detector()
    qtbot.waitUntil(lambda: not win._graph._loading, timeout=10000)


class _SeenWatching:
    """The real remove command, noting whether the window was watching when it ran.

    A flag, not the detector: a failed comparison would have to print a Qt
    object the window has already deleted.
    """

    def __init__(self, win: MainWindow) -> None:
        self._win = win
        self._real = win._commands.remove_worktree
        self.watching: list[bool] = []

    def execute(self, *args, **kwargs):
        self.watching.append(self._win._change_detector is not None)
        return self._real.execute(*args, **kwargs)


class _Refused:
    """A remove command git turns down, once *release* is set if there is one."""

    def __init__(self, release: threading.Event | None = None) -> None:
        self._release = release

    def execute(self, *_args, **_kwargs):
        if self._release is not None:
            self._release.wait(5)
        raise RuntimeError("refused by git")


def _relaunched_onto(qtbot, tmp_path, main: Path, worktree: str) -> MainWindow:
    """A window opened on *worktree*, whose repo *main* is open, past its start-up loads."""
    store = JsonRepoStore(tmp_path / "repos.json")
    store.add_open(str(main))
    store.set_active(worktree)
    win = _window_on(qtbot, worktree, store)
    _wait_for_the_start_up_loads(qtbot, win)
    return win


def _log_text(win: MainWindow) -> str:
    return win._log_panel._body.toPlainText()


def test_the_window_stops_watching_the_worktree_on_screen_while_git_removes_it(
    qtbot, tmp_path, monkeypatch
):
    """A reload the watch schedules runs `git status` in the worktree, and on
    Windows git then fails to delete the folder: 'Permission denied', with the
    worktree already unregistered and the window left on the dead path."""
    main, worktree = _repo_with_worktree(tmp_path)
    win = _relaunched_onto(qtbot, tmp_path, main, worktree)
    spy = _SeenWatching(win)
    monkeypatch.setattr(win._commands, "remove_worktree", spy)

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=10000):
        win._run_remove_worktree(worktree, force=False)

    assert spy.watching == [False]
    assert not Path(worktree).exists()
    assert Path(win._change_detector._repo_path) == main, "the repo it moved to is watched"
    _quiet(qtbot, win)


def test_a_refused_removal_of_the_worktree_on_screen_leaves_it_watched(
    qtbot, tmp_path, monkeypatch
):
    main, worktree = _repo_with_worktree(tmp_path)
    win = _relaunched_onto(qtbot, tmp_path, main, worktree)
    monkeypatch.setattr(win._commands, "remove_worktree", _Refused())

    win._run_remove_worktree(worktree, force=False)

    qtbot.waitUntil(
        lambda: "Remove worktree failed: refused by git" in _log_text(win), timeout=5000
    )
    assert win._change_detector is not None
    assert Path(win._change_detector._repo_path) == Path(worktree)
    _quiet(qtbot, win)


def test_a_refusal_that_comes_after_another_repo_opened_leaves_that_repos_watch(
    qtbot, tmp_path, monkeypatch
):
    """The watch to bring back would be of the worktree the window has left."""
    main, worktree = _repo_with_worktree(tmp_path)
    win = _relaunched_onto(qtbot, tmp_path, main, worktree)
    refuse = threading.Event()
    monkeypatch.setattr(win._commands, "remove_worktree", _Refused(refuse))
    win._run_remove_worktree(worktree, force=False)
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        win._switch_repo(str(main))
    watching_main = win._change_detector

    refuse.set()
    qtbot.waitUntil(
        lambda: "Remove worktree failed: refused by git" in _log_text(win), timeout=5000
    )

    assert win._change_detector is watching_main
    _quiet(qtbot, win)


def test_a_refusal_that_comes_after_the_window_was_emptied_starts_no_watch(
    qtbot, tmp_path, monkeypatch
):
    """With no repo on screen there is nothing to watch: starting one raised out
    of the refusal's slot, before the failure was shown."""
    main, worktree = _repo_with_worktree(tmp_path)
    win = _relaunched_onto(qtbot, tmp_path, main, worktree)
    refuse = threading.Event()
    monkeypatch.setattr(win._commands, "remove_worktree", _Refused(refuse))
    win._run_remove_worktree(worktree, force=False)
    win._enter_empty_state()  # the repo goes while git is still deciding

    refuse.set()
    qtbot.waitUntil(
        lambda: "Remove worktree failed: refused by git" in _log_text(win), timeout=5000
    )

    assert win._change_detector is None
    _quiet(qtbot, win)


def test_a_second_refusal_leaves_the_watch_the_first_one_brought_back(qtbot, tmp_path, monkeypatch):
    """Two removals refused: the first brings the watch back, and the second
    finds it running. Starting another would replace it for nothing."""
    main, worktree = _repo_with_worktree(tmp_path)
    win = _relaunched_onto(qtbot, tmp_path, main, worktree)
    started: list[str] = []
    start = win._start_change_detector

    def _start_noting(path: str) -> None:
        started.append(path)
        start(path)

    monkeypatch.setattr(win, "_start_change_detector", _start_noting)
    refuse = threading.Event()
    monkeypatch.setattr(win._commands, "remove_worktree", _Refused(refuse))
    win._run_remove_worktree(worktree, force=False)
    win._run_remove_worktree(worktree, force=False)

    refuse.set()
    qtbot.waitUntil(
        lambda: _log_text(win).count("Remove worktree failed: refused by git") == 2, timeout=5000
    )

    assert started == [worktree]
    _quiet(qtbot, win)


def test_removing_another_worktree_leaves_the_watch_alone(qtbot, tmp_path, monkeypatch):
    main, worktree = _repo_with_worktree(tmp_path)
    store = JsonRepoStore(tmp_path / "repos.json")
    store.add_open(str(main))
    win = _window_on(qtbot, str(main), store)
    watching = win._change_detector
    spy = _SeenWatching(win)
    monkeypatch.setattr(win._commands, "remove_worktree", spy)

    win._run_remove_worktree(worktree, force=False)

    qtbot.waitUntil(
        lambda: not Path(worktree).exists() and win._repo_list.owner_of(worktree) is None,
        timeout=10000,
    )
    assert spy.watching == [True]
    assert win._change_detector is watching
    _quiet(qtbot, win)


# ── A worktree written another way than git lists it ─────────────────────────


def _with_a_trailing_separator(path: str) -> str:
    return path + os.sep


def _with_forward_slashes(path: str) -> str:
    return path.replace("\\", "/")


_WRITTEN_ANOTHER_WAY = pytest.mark.parametrize(
    "respell",
    [
        pytest.param(_with_a_trailing_separator, id="trailing separator"),
        pytest.param(
            _with_forward_slashes,
            id="forward slashes",
            marks=pytest.mark.skipif(os.sep != "\\", reason="a separator on Windows only"),
        ),
    ],
)


@_WRITTEN_ANOTHER_WAY
def test_the_worktree_on_screen_is_left_when_git_lists_it_another_way(
    qtbot, tmp_path, monkeypatch, respell
):
    """The Open dialog writes forward slashes and git lists the folder with
    backslashes. The removal dropped the watch, then took the worktree for
    another one: the window stayed on the deleted folder, unwatched, and its
    row stayed in the open list."""
    main, worktree = _repo_with_worktree(tmp_path)
    store, far = _own_row_store(tmp_path, respell(worktree))
    win = _window_on(qtbot, respell(worktree), store)
    _wait_for_the_start_up_loads(qtbot, win)
    spy = _SeenWatching(win)
    monkeypatch.setattr(win._commands, "remove_worktree", spy)

    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=10000, raising=False):
        win._run_remove_worktree(worktree, force=False)

    assert spy.watching == [False], "the watch is dropped while git removes the folder"
    assert Path(win._repo_path) == main.resolve()
    assert Path(win._change_detector._repo_path) == main.resolve(), (
        "the repo it moved to is watched"
    )
    assert store.get_open_repos() == [far, win._repo_path], "main takes the dead row's place"
    _quiet(qtbot, win)


@_WRITTEN_ANOTHER_WAY
def test_the_open_row_of_a_removed_worktree_is_dropped_however_it_was_written(
    qtbot, tmp_path, respell
):
    """The child row asks git to remove the folder as git lists it, and the
    open row the Open dialog wrote did not match: it stayed, for a folder that
    is gone."""
    main, worktree = _repo_with_worktree(tmp_path)
    store = JsonRepoStore(tmp_path / "repos.json")
    store.add_open(respell(worktree))
    store.add_open(str(main))
    win = _window_on(qtbot, str(main), store)
    _wait_for_the_start_up_loads(qtbot, win)

    win._run_remove_worktree(worktree, force=False)

    qtbot.waitUntil(
        lambda: not Path(worktree).exists() and win._repo_list.owner_of(worktree) is None,
        timeout=10000,
    )
    assert store.get_open_repos() == [str(main)]
    _quiet(qtbot, win)


# ── Ctrl+W while the replacement of a removed worktree opens ─────────────────


def test_ctrl_w_while_the_removed_worktree_is_being_replaced_leaves_the_screen_alone(
    qtbot, tmp_path
):
    """The worktree is gone and main is on its way to take its place. Ctrl+W
    closed the dead folder as a repo of its own: it was listed under RECENT,
    where clicking it fails, and the window went blank until main opened."""
    from main import _open_session

    main, worktree = _repo_with_worktree(tmp_path)
    store, _ = _own_row_store(tmp_path, worktree)
    release = threading.Event()

    def _main_held(path: str):
        if Path(path) == main.resolve():
            release.wait(5)
        return _open_session(path)

    win = _window_on(qtbot, worktree, store, session_factory=_main_held)
    _git_removes_the_worktree(qtbot, win, main, worktree)
    win._on_worktree_removed(worktree)

    win._close_current_repo()

    assert store.get_recent_repos() == []
    assert Path(win._repo_path) == Path(worktree), "the window stays until main opens"
    with qtbot.waitSignal(win._repo_ready_signals.ready, timeout=5000):
        release.set()
    assert Path(win._repo_path) == main.resolve()
    assert store.get_recent_repos() == []
    _quiet(qtbot, win)
