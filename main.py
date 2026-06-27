import logging
import sys
from pathlib import Path

import pygit2
from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from git_gui.infrastructure.pygit2 import Pygit2Repository
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.logging_setup import setup_logging
from git_gui.observability import init_crash_reporting
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.main_window import MainWindow
from git_gui.presentation.theme import ThemeManager, set_theme_manager


def _is_git_repo(path: str) -> bool:
    return pygit2.discover_repository(path) is not None


def _find_valid_repo(repo_store: JsonRepoStore) -> str | None:
    """Return a valid repo to open, pruning every stored path that no longer
    resolves to a git repository.

    Pruning scans the *entire* open and recent lists — not just up to the first
    valid entry — so stale paths (e.g. a deleted worktree) never linger across
    sessions, rendering as repo rows that fail with "Repository not found" when
    switched to. Returns the active repo if still valid, otherwise the first
    surviving open repo, otherwise None.
    """

    def _valid(p: str | None) -> bool:
        return bool(p) and Path(p).is_dir() and _is_git_repo(p)

    for path in list(repo_store.get_open_repos()) + list(repo_store.get_recent_repos()):
        if not _valid(path):
            repo_store.forget(path)

    # Keep a still-valid active repo even if it isn't in the open list (e.g. an
    # active worktree, recorded via set_active without add_open). Otherwise fall
    # back to the first surviving open repo.
    active = repo_store.get_active()
    if _valid(active):
        selected = active
    else:
        if active is not None:
            repo_store.forget(active)  # clear a dead active not in open/recent
        open_repos = repo_store.get_open_repos()
        selected = open_repos[0] if open_repos else None

    if selected is not None:
        repo_store.set_active(selected)

    repo_store.save()
    return selected


def _open_session(path: str) -> tuple[QueryBus, CommandBus]:
    repo = Pygit2Repository(path)
    return QueryBus.from_reader(repo), CommandBus.from_writer(repo)


_SUPPRESSED_FRAGMENTS = (
    "Unable to open monitor interface",
    "cached device pixel ratio value was stale",
)


def _qt_message_filter(mode, context, message):
    """Filter out known-noisy Qt platform warnings (Windows QPA bugs)."""
    if any(fragment in message for fragment in _SUPPRESSED_FRAGMENTS):
        logging.debug("Suppressed Qt warning: %s", message)
        return
    sys.stderr.write(f"Qt {mode.name}: {message}\n")


def main() -> None:
    setup_logging()
    init_crash_reporting()
    qInstallMessageHandler(_qt_message_filter)
    app = QApplication(sys.argv)
    app.setOrganizationName("GitCrisp")
    app.setApplicationName("GitCrisp")

    theme_manager = ThemeManager(app)
    set_theme_manager(theme_manager)

    repo_store = JsonRepoStore()
    repo_store.load()
    remote_tag_cache = JsonRemoteTagCache()

    repo_path = _find_valid_repo(repo_store)

    if repo_path and repo_path not in repo_store.get_open_repos():
        repo_store.add_open(repo_path)
        repo_store.save()

    if repo_path:
        queries, commands = _open_session(repo_path)
    else:
        queries, commands = None, None

    window = MainWindow(
        queries,
        commands,
        repo_store,
        remote_tag_cache,
        repo_path,
        session_factory=_open_session,
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
