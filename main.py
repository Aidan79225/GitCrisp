import logging
import sys
from pathlib import Path

import pygit2
from PySide6.QtCore import QtMsgType, qInstallMessageHandler
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
from git_gui.resources import get_resource_path


def _is_git_repo(path: str) -> bool:
    return pygit2.discover_repository(path) is not None


def _is_stale(path: str) -> bool:
    """Whether *path* is gone for good, rather than out of reach for now.

    A path that is there but no longer a repository is stale, and so is one
    deleted from a folder that is still there (a removed worktree). One whose
    parent is missing too sits on a drive, share or mount that is not there
    right now, and is kept for when it is.
    """
    stored = Path(path)
    if stored.is_dir():
        return not _is_git_repo(path)
    return stored.parent.is_dir()


def _find_valid_repo(repo_store: JsonRepoStore) -> str | None:
    """Return a valid repo to open, pruning every stored path that is stale.

    Pruning scans the *entire* open and recent lists — not just up to the first
    valid entry — so stale paths (e.g. a deleted worktree) never linger across
    sessions, rendering as repo rows that fail with "Repository not found" when
    switched to. Returns the active repo if still valid, otherwise the first
    valid open repo, otherwise None.
    """

    def _valid(p: str | None) -> bool:
        return bool(p) and Path(p).is_dir() and _is_git_repo(p)

    for path in list(repo_store.get_open_repos()) + list(repo_store.get_recent_repos()):
        if _is_stale(path):
            repo_store.forget(path)

    # Keep a still-valid active repo even if it isn't in the open list (e.g. an
    # active worktree, recorded via set_active without add_open). Otherwise fall
    # back to the first valid open repo.
    active = repo_store.get_active()
    if _valid(active):
        selected = active
    else:
        if active is not None and _is_stale(active):
            repo_store.forget(active)  # clear a dead active not in open/recent
        selected = next((p for p in repo_store.get_open_repos() if _valid(p)), None)

    if selected is not None:
        repo_store.set_active(selected)

    repo_store.save()
    return selected


def _open_session(path: str) -> tuple[QueryBus, CommandBus]:
    repo = Pygit2Repository(path)
    return QueryBus.from_reader(repo), CommandBus.from_writer(repo)


def _open_startup_session(path: str) -> tuple[QueryBus, CommandBus] | None:
    """The session to start in, or None when *path* will not open.

    discover_repository, which validated the path, accepts repositories that
    pygit2 then refuses to open — a reftable or sha256 repo, a config that does
    not parse. The path stays stored and active, so an error escaping here
    would stop every launch. It is kept rather than forgotten: a broken config
    is fixable, and switching to it from the repo list shows the error.
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
    remote_tag_cache = JsonRemoteTagCache()

    repo_path = _find_valid_repo(repo_store)

    if repo_path and repo_path not in repo_store.get_open_repos():
        repo_store.add_open(repo_path)
        repo_store.save()

    session = _open_startup_session(repo_path) if repo_path else None
    queries, commands = session or (None, None)

    window = MainWindow(
        queries,
        commands,
        repo_store,
        remote_tag_cache,
        repo_path if session else None,
        session_factory=_open_session,
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
