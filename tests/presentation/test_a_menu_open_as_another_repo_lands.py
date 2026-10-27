"""An entry picked from a context menu open as another repo lands acts on neither repo.

A menu runs a nested event loop, and a repo switch already on its way (an
open on a network share can take seconds) lands inside it. The window then
holds the new repo's buses, but the row the user right-clicked was the old
repo's: Drop and Pop took the new repo's stash of that number, Delete branch
its branch of that name, and the commit pane's Blame and Show file history
opened the new repo's file of that path.

The menus here are real ones, so B's queued repo-ready lands in their loop
exactly as it does in the app.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.presentation.main_window import MainWindow
from git_gui.presentation.main_window.repo_lifecycle import _RepoRequest, _SwitchReason
from git_gui.presentation.models.graph_model import INFO_ROLE
from git_gui.presentation.widgets.avatar_loader import get_avatar_loader

_FILE = "secret.txt"


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)
    return done.stdout.decode()


def _commit(path: Path, text: str, message: str) -> None:
    (path / _FILE).write_text(text)
    _git(path, "add", _FILE)
    _git(path, "commit", "-qm", message)


def _repo(path: Path) -> str:
    """'topic' alone on one commit, 'left' and 'right' on the next, master
    on top of them, and two stashes."""
    path.mkdir()
    _git(path, "init", "-q", "-b", "master", ".")
    _git(path, "config", "user.name", "T")
    _git(path, "config", "user.email", "t@e.com")
    _commit(path, "one\n", "first")
    _git(path, "branch", "topic")
    _commit(path, "two\n", "second")
    _git(path, "branch", "left")
    _git(path, "branch", "right")
    _commit(path, "three\n", "third")
    for n in range(2):
        (path / _FILE).write_text(f"{path.name} stash {n}\n")
        _git(path, "stash", "push", "-q", "-m", f"{path.name} stash {n}")
    return str(path)


def _stashes_and_changes(repo: str) -> tuple[list[str], str]:
    """Its stashes, and the changes in its working tree that Apply and Pop make."""
    stashes = _git(Path(repo), "stash", "list", "--format=%s").splitlines()
    return stashes, _git(Path(repo), "status", "--porcelain")


def _has_branch(repo: str, name: str) -> bool:
    return bool(_git(Path(repo), "branch", "--list", name).strip())


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Keep the commit pane's author avatar off the network: a Gravatar
    request still in flight when the window goes crashed a later test."""
    monkeypatch.setattr(get_avatar_loader(), "_start_fetch", lambda _email_hash: None)


@pytest.fixture
def repos(tmp_path) -> tuple[str, str]:
    return _repo(tmp_path / "a"), _repo(tmp_path / "b")


@pytest.fixture
def win(qtbot, tmp_path, repos) -> MainWindow:
    """The window on repo A, both repos open, its commit list loaded."""
    from main import _open_session

    repo_a, repo_b = repos
    store = JsonRepoStore(tmp_path / "repos.json")
    store.add_open(repo_b)
    store.add_open(repo_a)
    queries, commands = _open_session(repo_a)
    w = MainWindow(
        queries, commands, store, JsonRemoteTagCache(), repo_a, session_factory=_open_session
    )
    qtbot.addWidget(w)
    w.show()
    qtbot.waitUntil(lambda: _graph_row_of(w, "topic") is not None, timeout=5000)
    return w


def _graph_row_of(win: MainWindow, branch: str) -> int | None:
    model = win._graph._model
    for row in range(model.rowCount()):
        info = model.data(model.index(row, 0), INFO_ROLE)
        if info is not None and branch in info.branch_names:
            return row
    return None


# ── Working a real menu from inside its loop ─────────────────────────────────


def _action(menu: QMenu, text: str) -> QAction | None:
    return next((a for a in menu.actions() if a.text() == text), None)


def _close_every_menu() -> None:
    while (menu := QApplication.activePopupWidget()) is not None:
        menu.close()


class _MenuUser:
    """Works one of A's menus from inside its loop, as the user would with the keys.

    With the menu up, and the submenus on *path* open, it calls *ask*; once
    *arrived* says the answer has landed, it picks *path* from whichever menu
    is still open: a submenu's title and an entry in it, or an entry alone.
    """

    def __init__(
        self, path: tuple[str, ...], ask: Callable[[], None], arrived: Callable[[], bool]
    ) -> None:
        self._path, self._ask, self._arrived = path, ask, arrived
        self._asked = False
        self._deadline = time.monotonic() + 5
        self._timer = QTimer()
        self._timer.timeout.connect(self._step)

    def use(self, open_menu: Callable[[], None]) -> None:
        self._timer.start(10)
        open_menu()
        self._timer.stop()
        assert self._arrived(), "the answer was to land while the menu was up"

    def _step(self) -> None:
        menu = QApplication.activePopupWidget()
        if not self._asked:
            if menu is not None:
                self._open_submenus(menu)
                self._ask()
                self._asked = True
            return
        arrived = self._arrived()
        if not arrived and time.monotonic() < self._deadline:
            return
        self._timer.stop()
        if menu is None:
            return  # closed as the answer landed: nothing is left to pick
        if arrived:
            self._pick(menu)
        _close_every_menu()  # never leave the test waiting in the loop

    def _open_submenus(self, menu: QMenu) -> QMenu:
        for title in self._path[:-1]:
            menu.setActiveAction(_action(menu, title))
            QTest.keyClick(menu, Qt.Key_Right)
            menu = QApplication.activePopupWidget()
        return menu

    def _pick(self, menu: QMenu) -> None:
        if _action(menu, self._path[-1]) is None:
            menu = self._open_submenus(menu)  # a parent was left open: go back in
        menu.setActiveAction(_action(menu, self._path[-1]))
        QTest.keyClick(menu, Qt.Key_Return)


def _as_b_lands(win: MainWindow, repo_b: str, *path: str) -> _MenuUser:
    """Asks for B from inside the menu, and picks *path* once B is on screen."""
    return _MenuUser(path, lambda: win._switch_repo(repo_b), lambda: win._repo_path == repo_b)


# ── Sidebar ──────────────────────────────────────────────────────────────────


def _stash_menu(win: MainWindow, index: str, monkeypatch) -> Callable[[], None]:
    """Right-clicking stash@{*index*} in the sidebar."""
    sidebar = win._sidebar
    model = sidebar._model
    header = next(
        model.item(r) for r in range(model.rowCount()) if model.item(r).text() == "STASHES"
    )
    row = next(
        header.child(r)
        for r in range(header.rowCount())
        if header.child(r).data(Qt.UserRole) == index
    )
    monkeypatch.setattr(sidebar._tree, "indexAt", lambda _pos: row.index())
    return lambda: sidebar._show_context_menu(QPoint(1, 1))


@pytest.mark.parametrize("choice", ["Pop", "Apply", "Drop"])
def test_a_stash_entry_picked_as_another_repo_lands_touches_neither_stash(
    qtbot, win, repos, monkeypatch, choice
):
    repo_a, repo_b = repos
    qtbot.waitUntil(lambda: win._sidebar._model.rowCount() > 0, timeout=5000)
    before = _stashes_and_changes(repo_a), _stashes_and_changes(repo_b)
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.Yes)

    _as_b_lands(win, repo_b, choice).use(_stash_menu(win, "1", monkeypatch))

    assert (_stashes_and_changes(repo_a), _stashes_and_changes(repo_b)) == before


# ── Commit list ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "branch, path",
    [("topic", ("Delete branch: topic",)), ("left", ("Delete branch", "left"))],
    ids=["alone", "in-a-submenu"],
)
def test_a_branch_delete_picked_as_another_repo_lands_deletes_neither_branch(
    win, repos, monkeypatch, branch, path
):
    repo_a, repo_b = repos
    graph = win._graph
    row = graph._model.index(_graph_row_of(win, branch), 0)
    monkeypatch.setattr(graph._view, "indexAt", lambda _pos: row)
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.Yes)

    _as_b_lands(win, repo_b, *path).use(lambda: graph._show_context_menu(QPoint(1, 1)))

    assert _has_branch(repo_a, branch) and _has_branch(repo_b, branch)


# ── Commit pane ──────────────────────────────────────────────────────────────


def _file_list_menu(win: MainWindow) -> Callable[[], None]:
    navigator = win._diff._file_navigator
    return lambda: navigator._show_file_menu(win.mapToGlobal(QPoint(40, 40)), _FILE)


def _file_header_menu(win: MainWindow) -> Callable[[], None]:
    return lambda: win._diff._show_file_header_menu(win.mapToGlobal(QPoint(40, 40)), _FILE)


@pytest.mark.parametrize("menu", [_file_list_menu, _file_header_menu], ids=["list", "header"])
@pytest.mark.parametrize("choice", ["Blame this file", "Show file history"])
def test_a_view_picked_in_the_commit_pane_as_another_repo_lands_opens_nothing(
    qtbot, win, repos, menu, choice
):
    """B may have a file of the same name, and its blame or history is not A's."""
    repo_a, repo_b = repos
    win._diff.load_commit(_git(Path(repo_a), "rev-parse", "HEAD").strip())
    qtbot.waitUntil(lambda: win._diff._diff_model.rowCount() == 1, timeout=5000)

    _as_b_lands(win, repo_b, choice).use(menu(win))

    assert win._blame_pane is None
    assert win._graph._path_filter is None


# ── The window left empty ────────────────────────────────────────────────────


def test_a_stash_entry_picked_as_the_window_empties_runs_nowhere(qtbot, win, tmp_path, monkeypatch):
    """A repo replacing a closed one that fails to open leaves no buses at all:
    the pick reached a handler with none, which logged an AttributeError."""
    qtbot.waitUntil(lambda: win._sidebar._model.rowCount() > 0, timeout=5000)
    gone = _RepoRequest(str(tmp_path / "gone"), _SwitchReason.REPLACE)
    user = _MenuUser(("Pop",), lambda: win._request_repo(gone), lambda: win._repo_path is None)

    user.use(_stash_menu(win, "1", monkeypatch))

    assert "Stash pop" not in win._log_panel._body.toPlainText()
