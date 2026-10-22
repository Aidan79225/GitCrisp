import logging
import sys
import threading
from collections.abc import Callable, Iterable, Iterator
from enum import Enum, auto
from pathlib import Path
from typing import NamedTuple

import pygit2
from PySide6.QtCore import QObject, QtMsgType, Signal, qInstallMessageHandler
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from git_gui.infrastructure.pygit2 import Pygit2Repository
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.logging_setup import setup_logging
from git_gui.observability import init_crash_reporting
from git_gui.presentation.app_settings import get_send_crash_reports
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.main_window import MainWindow
from git_gui.presentation.theme import ThemeManager, set_theme_manager
from git_gui.presentation.widgets.log_panel import LogPanel
from git_gui.presentation.widgets.repo_list import RepoListWidget
from git_gui.resources import get_resource_path


def _is_git_repo(path: str) -> bool:
    return pygit2.discover_repository(path) is not None


class _StoredRepo(Enum):
    PRESENT = auto()
    GONE = auto()
    OUT_OF_REACH = auto()


def _stored_repo_state(path: str) -> _StoredRepo:
    """Whether *path* is a repo, gone for good, or out of reach for now.

    A path that is there but no longer a repository is gone, and so is one
    deleted from a folder that is still there (a removed worktree). One whose
    parent is missing too sits on a drive, share or mount that is not there
    right now, and is kept for when it is. The parent is probed first because
    on an unreachable share each probe waits out a network timeout.
    """
    stored = Path(path)
    if not stored.parent.is_dir():
        return _StoredRepo.OUT_OF_REACH
    if stored.is_dir() and _is_git_repo(path):
        return _StoredRepo.PRESENT
    return _StoredRepo.GONE


class _Startup(NamedTuple):
    """The repo the window starts on, with its session."""

    path: str
    queries: QueryBus
    commands: CommandBus


def _open_startup_repo(repo_store: JsonRepoStore) -> _Startup | None:
    """Open the repo to start in: the active one if it still opens, otherwise
    the first open repo that does, which becomes the active one; or None.

    This runs before the window shows, and each probe of a path on an
    unreachable share waits out a network timeout, so candidates are probed
    one at a time and only until one opens. The other stored paths are left
    to _GoneRepoPruner.

    A repo that is there but will not open is passed over rather than left
    active: the repo list would draw it as the repo on screen and ignore
    clicks on it, leaving no way to reach it or its error.
    """
    started = _first_that_opens(_present_repos(repo_store, _startup_candidates(repo_store)))
    if started is not None:
        repo_store.set_active(started.path)
    return started


def _startup_candidates(repo_store: JsonRepoStore) -> list[str]:
    # The active repo leads even when it is not an open one: switching to a
    # linked worktree records it with set_active alone.
    active = repo_store.get_active()
    return list(dict.fromkeys(([active] if active else []) + repo_store.get_open_repos()))


def _present_repos(repo_store: JsonRepoStore, paths: Iterable[str]) -> Iterator[str]:
    """Each of *paths* that is a repo, forgetting the ones found gone on the way."""
    for path in paths:
        state = _stored_repo_state(path)
        if state is _StoredRepo.GONE:
            repo_store.forget(path)
        elif state is _StoredRepo.PRESENT:
            yield path


def _first_that_opens(paths: Iterable[str]) -> _Startup | None:
    for path in paths:
        session = _open_startup_session(path)
        if session is not None:
            return _Startup(path, *session)
    return None


class _GoneRepoPruner(QObject):
    """Forgets every stored repo that is gone, probing them off the GUI thread.

    All of the open and recent lists are scanned, so stale paths (a deleted
    worktree, say) never linger across sessions as rows that fail with
    "Repository not found" when switched to. A path out of reach is kept for
    when it is back, so it is probed on every launch, and on an unreachable
    share each probe waits out a network timeout: that is why this runs once
    the window is up rather than before it.
    """

    _found_gone = Signal(list)

    def __init__(
        self,
        repo_store: JsonRepoStore,
        on_pruned: Callable[[], None],
        on_save_failed: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo_store = repo_store
        self._on_pruned = on_pruned
        self._on_save_failed = on_save_failed
        self._found_gone.connect(self._forget)

    def start(self) -> None:
        paths = _stored_paths(self._repo_store)
        # Each path found gone is probed again once the rest are done: a share
        # out of reach can hold this for minutes, by which time the path may be
        # a repo again, cloned back or re-added as a worktree.
        threading.Thread(
            target=lambda: self._found_gone.emit(_gone(_gone(paths))), daemon=True
        ).start()

    def _forget(self, gone: list[str]) -> None:
        # The repo on screen is kept whatever its probe found: forgetting it
        # would drop its row while its panes are still up. If it is still gone
        # at the next launch, the startup forgets it.
        active = self._repo_store.get_active()
        gone = [path for path in gone if path != active]
        if not gone:
            return
        for path in gone:
            self._repo_store.forget(path)
        _save_repo_store(self._repo_store, self._on_save_failed)
        self._on_pruned()


def _stored_paths(repo_store: JsonRepoStore) -> list[str]:
    active = repo_store.get_active()
    stored = repo_store.get_open_repos() + repo_store.get_recent_repos()
    return list(dict.fromkeys(stored + ([active] if active else [])))


def _gone(paths: Iterable[str]) -> list[str]:
    return [path for path in paths if _stored_repo_state(path) is _StoredRepo.GONE]


def _open_session(path: str) -> tuple[QueryBus, CommandBus]:
    repo = Pygit2Repository(path)
    return QueryBus.from_reader(repo), CommandBus.from_writer(repo)


def _open_startup_session(path: str) -> tuple[QueryBus, CommandBus] | None:
    """The session to start in, or None when *path* will not open.

    discover_repository, which validated the path, accepts repositories that
    pygit2 then refuses to open — a reftable or sha256 repo, a config that does
    not parse. The path stays stored, so an error escaping here would stop
    every launch. It is kept rather than forgotten: a broken config is
    fixable, and switching to it from the repo list shows the error.
    """
    try:
        return _open_session(path)
    except pygit2.GitError as e:
        logging.warning("Cannot open %s at startup: %s", path, e)
        return None


_SUPPRESSED_FRAGMENTS = (
    "Unable to open monitor interface",
    "cached device pixel ratio value was stale",
)


_QT_LOG_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


def _qt_message_filter(mode, context, message):
    """Filter out known-noisy Qt platform warnings (Windows QPA bugs).

    Qt calls this from inside whatever code provoked the message, so anything
    raised here surfaces there instead — a Qt warning becomes an exception in
    an unrelated widget. A released GitCrisp is a windowed build (PyInstaller
    ``--windowed``, like ``pythonw``), which has no stderr at all, so writing
    to it unguarded did exactly that: a missing-icon warning while a hunk block
    was being built came back as an ``AttributeError`` and stopped the
    working-tree diff rendering.

    The log is therefore the sink that has to work, and stderr is the extra.
    """
    if any(fragment in message for fragment in _SUPPRESSED_FRAGMENTS):
        logging.debug("Suppressed Qt warning: %s", message)
        return
    logging.log(_QT_LOG_LEVELS.get(mode, logging.WARNING), "Qt %s: %s", mode.name, message)
    if sys.stderr is not None:
        sys.stderr.write(f"Qt {mode.name}: {message}\n")


def main() -> None:
    setup_logging()
    qInstallMessageHandler(_qt_message_filter)
    app = QApplication(sys.argv)
    app.setOrganizationName("GitCrisp")
    app.setApplicationName("GitCrisp")
    # After the names above: the opt-out lives in QSettings, which is keyed
    # by them.
    init_crash_reporting(enabled=get_send_crash_reports())
    # Windows takes the running app's icon from the exe and macOS from the
    # bundle, so this is really for Linux, where a window manager that cannot
    # match the window back to its .desktop entry falls back to a generic
    # placeholder. Qt is handed the SVG rather than the .ico so it can rasterise
    # at whatever size the desktop asks for, and so the icon has one source.
    app.setWindowIcon(QIcon(str(get_resource_path("arts") / "gitcrisp.svg")))

    theme_manager = ThemeManager(app)
    set_theme_manager(theme_manager)

    repo_store = JsonRepoStore()
    repo_store.load()
    window = _open_window(repo_store, JsonRemoteTagCache())
    window.show()
    _GoneRepoPruner(
        repo_store,
        on_pruned=lambda: _reload_repo_list(window),
        on_save_failed=lambda reason: _report_unsaved_repo_list(window, reason),
        parent=window,
    ).start()
    sys.exit(app.exec())


def _reload_repo_list(window: MainWindow) -> None:
    # The list on screen was drawn from the store before the pruning finished.
    window.findChild(RepoListWidget).reload()


def _open_window(repo_store: JsonRepoStore, remote_tag_cache: JsonRemoteTagCache) -> MainWindow:
    """The main window, on the repo the last session left active if it still opens."""
    repo_path, queries, commands = _open_startup_repo(repo_store) or (None, None, None)
    window = MainWindow(
        queries,
        commands,
        repo_store,
        remote_tag_cache,
        repo_path,
        session_factory=_open_session,
    )
    _save_repo_store(repo_store, on_failed=lambda reason: _report_unsaved_repo_list(window, reason))
    return window


def _save_repo_store(repo_store: JsonRepoStore, on_failed: Callable[[str], None]) -> None:
    """Write the repo list out, handing a failed write to *on_failed* rather than raising.

    save() raises when repos.json cannot be written (read-only, locked by a
    sync client, a full disk) and on every call after load() could not read
    it. At launch that error left main() before the window showed, so GitCrisp
    would not start until the file was fixed by hand. The in-memory store is
    right either way, and the next save tries again.
    """
    try:
        repo_store.save()
    except OSError as e:
        on_failed(str(e))


def _report_unsaved_repo_list(window: MainWindow, reason: str) -> None:
    # Worded as the window reports its own failed saves of the list.
    log_panel = window.findChild(LogPanel)
    log_panel.expand()
    log_panel.log_error(f"Could not save the repo list: {reason}")


if __name__ == "__main__":
    main()
